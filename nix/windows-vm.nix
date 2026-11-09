{ pkgs }:
pkgs.writeShellApplication {
  name = "zen-bonsai-windows-vm";
  runtimeInputs = with pkgs; [
    coreutils
    qemu
    swtpm
    util-linux
  ];
  text = ''
    state="''${WIN11_STATE_DIR:-/mnt/data2/vms/windows11}"
    iso="''${1:-}"
    answer_iso="''${WIN11_ANSWER_ISO:-}"
    if [[ -n "$iso" && ! -r "$iso" ]]; then
      echo "Cannot read Windows installer: $iso" >&2
      exit 1
    fi
    if [[ -n "$answer_iso" && ! -r "$answer_iso" ]]; then
      echo "Cannot read unattended setup image: $answer_iso" >&2
      exit 1
    fi
    if [[ "$state$iso$answer_iso" == *,* ]]; then
      echo "QEMU drive paths must not contain commas" >&2
      exit 1
    fi
    if [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then
      echo "This VM needs read/write access to /dev/kvm" >&2
      exit 1
    fi

    umask 077
    mkdir -p "$state/tpm"
    # One VM process must own the disk, firmware variables and TPM together.
    exec 9>"$state/vm.lock"
    if ! flock -n 9; then
      echo "The Windows VM is already running in $state" >&2
      exit 1
    fi
    if [[ ! -e "$state/windows11.qcow2" ]]; then
      qemu-img create -f qcow2 "$state/windows11.qcow2" 96G
    fi
    if [[ ! -e "$state/OVMF_VARS.fd" ]]; then
      cp ${pkgs.OVMFFull.fd}/FV/OVMF_VARS.fd "$state/OVMF_VARS.fd"
      chmod u+w "$state/OVMF_VARS.fd"
    fi

    swtpm socket --tpm2 --tpmstate "dir=$state/tpm" \
      --ctrl "type=unixio,path=$state/swtpm.sock" --flags not-need-init &
    tpm_pid=$!
    trap 'kill "$tpm_pid" 2>/dev/null || true; wait "$tpm_pid" 2>/dev/null || true' EXIT
    for _ in $(seq 1 100); do
      [[ -S "$state/swtpm.sock" ]] && break
      kill -0 "$tpm_pid"
      sleep 0.1
    done
    if [[ ! -S "$state/swtpm.sock" ]]; then
      echo "TPM did not start" >&2
      exit 1
    fi

    media=()
    if [[ -n "$iso" ]]; then
      media+=(-drive "file=$iso,media=cdrom,readonly=on")
    fi
    if [[ -n "$answer_iso" ]]; then
      media+=(-drive "file=$answer_iso,media=cdrom,readonly=on")
    fi
    echo "Windows VM: VNC 127.0.0.1:5911; SSH 127.0.0.1:22222; RDP 127.0.0.1:23389"
    # Only local clients can reach the forwarded guest services or display.
    qemu-system-x86_64 \
      -name zen-bonsai-windows11 -machine q35,accel=kvm,smm=on -cpu host \
      -smp "''${WIN11_CPUS:-4}" -m "''${WIN11_MEMORY:-8G}" \
      -drive if=pflash,format=raw,unit=0,readonly=on,file=${pkgs.OVMFFull.fd}/FV/OVMF_CODE.fd \
      -drive "if=pflash,format=raw,unit=1,file=$state/OVMF_VARS.fd" \
      -drive "file=$state/windows11.qcow2,format=qcow2" \
      -chardev "socket,id=chrtpm,path=$state/swtpm.sock" \
      -tpmdev emulator,id=tpm0,chardev=chrtpm -device tpm-tis,tpmdev=tpm0 \
      -netdev user,id=network,hostfwd=tcp:127.0.0.1:22222-:22,hostfwd=tcp:127.0.0.1:23389-:3389 \
      -device e1000e,netdev=network -device qemu-xhci -device usb-tablet \
      -display none -vnc 127.0.0.1:11 \
      -qmp "unix:$state/qmp.sock,server=on,wait=off" \
      "''${media[@]}"
  '';
}

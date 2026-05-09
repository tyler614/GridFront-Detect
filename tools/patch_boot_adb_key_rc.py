#!/usr/bin/env python3
"""Create a Magisk boot image that installs this laptop's ADB key at boot.

Magisk supports rootdir overlays from ramdisk `overlay.d`. Files named
`overlay.d/*.rc` are injected into init, which lets us run a tiny init action
as root after /data is mounted. This is a recovery-only bridge for the
GridFront tablet kiosk case where the Android ADB authorization dialog is
trapped behind the app.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import stat
import struct
import time
from dataclasses import dataclass
from pathlib import Path


BOOT_MAGIC = b"ANDROID!"
CPIO_MAGIC = b"070701"


@dataclass(frozen=True)
class BootInfo:
    kernel_size: int
    ramdisk_size: int
    page_size: int
    ramdisk_offset: int


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) // boundary * boundary


def parse_boot(image: bytes) -> BootInfo:
    if image[:8] != BOOT_MAGIC:
        raise ValueError("missing Android boot magic")
    kernel_size = struct.unpack_from("<I", image, 8)[0]
    ramdisk_size = struct.unpack_from("<I", image, 16)[0]
    page_size = struct.unpack_from("<I", image, 36)[0]
    ramdisk_offset = page_size + align(kernel_size, page_size)
    if ramdisk_offset + ramdisk_size > len(image):
        raise ValueError("ramdisk extends beyond boot image")
    return BootInfo(kernel_size, ramdisk_size, page_size, ramdisk_offset)


def gzip_payload(payload: bytes) -> bytes:
    out = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=9, mtime=0) as gz:
        gz.write(payload)
    return out.getvalue()


def cpio_newc_entry(name: str, data: bytes, mode: int, mtime: int) -> bytes:
    namesize = len(name.encode("utf-8")) + 1
    fields = [
        CPIO_MAGIC,
        f"{0:08x}".encode(),
        f"{mode:08x}".encode(),
        f"{0:08x}".encode(),
        f"{0:08x}".encode(),
        f"{1:08x}".encode(),
        f"{mtime:08x}".encode(),
        f"{len(data):08x}".encode(),
        f"{0:08x}".encode(),
        f"{0:08x}".encode(),
        f"{0:08x}".encode(),
        f"{0:08x}".encode(),
        f"{namesize:08x}".encode(),
        f"{0:08x}".encode(),
    ]
    header = b"".join(fields)
    if len(header) != 110:
        raise AssertionError("bad cpio header length")
    out = bytearray(header)
    out += name.encode("utf-8") + b"\0"
    out += b"\0" * ((4 - (len(out) % 4)) % 4)
    out += data
    out += b"\0" * ((4 - (len(out) % 4)) % 4)
    return bytes(out)


def find_trailer(cpio: bytes) -> int:
    pos = 0
    while pos + 110 <= len(cpio):
        header = cpio[pos : pos + 110]
        if header[:6] != CPIO_MAGIC:
            raise ValueError(f"invalid cpio header at {pos}")
        filesize = int(header[54:62], 16)
        namesize = int(header[94:102], 16)
        name_start = pos + 110
        name_end = name_start + namesize
        name = cpio[name_start:name_end].rstrip(b"\0").decode("utf-8", "replace")
        file_start = align(name_end, 4)
        file_end = file_start + filesize
        if name == "TRAILER!!!":
            return pos
        pos = align(file_end, 4)
    raise ValueError("TRAILER!!! not found")


def remove_existing_entry(cpio: bytes, target: str) -> bytes:
    pos = 0
    out = bytearray()
    while pos + 110 <= len(cpio):
        header = cpio[pos : pos + 110]
        if header[:6] != CPIO_MAGIC:
            raise ValueError(f"invalid cpio header at {pos}")
        filesize = int(header[54:62], 16)
        namesize = int(header[94:102], 16)
        name_start = pos + 110
        name_end = name_start + namesize
        name = cpio[name_start:name_end].rstrip(b"\0").decode("utf-8", "replace")
        file_start = align(name_end, 4)
        file_end = file_start + filesize
        entry_end = align(file_end, 4)
        if name != target:
            out += cpio[pos:entry_end]
        pos = entry_end
        if name == "TRAILER!!!":
            break
    return bytes(out)


def compact_text_entries(cpio: bytes) -> bytes:
    pos = 0
    out = bytearray()
    changed = False
    while pos + 110 <= len(cpio):
        header = cpio[pos : pos + 110]
        if header[:6] != CPIO_MAGIC:
            raise ValueError(f"invalid cpio header at {pos}")
        filesize = int(header[54:62], 16)
        namesize = int(header[94:102], 16)
        mode = int(header[14:22], 16)
        mtime = int(header[46:54], 16)
        name_start = pos + 110
        name_end = name_start + namesize
        name = cpio[name_start:name_end].rstrip(b"\0").decode("utf-8", "replace")
        file_start = align(name_end, 4)
        file_end = file_start + filesize
        entry_end = align(file_end, 4)

        if name == "prop.default":
            text = cpio[file_start:file_end].decode("utf-8", "replace")
            lines = []
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                lines.append(stripped)
            data = ("\n".join(lines) + "\n").encode("utf-8")
            out += cpio_newc_entry(name, data, mode, mtime)
            changed = True
        elif name.endswith(".rc"):
            text = cpio[file_start:file_end].decode("utf-8", "replace")
            lines = []
            for line in text.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                lines.append(line.rstrip())
            data = ("\n".join(lines) + "\n").encode("utf-8")
            out += cpio_newc_entry(name, data, mode, mtime)
            changed = True
        else:
            out += cpio[pos:entry_end]

        pos = entry_end
        if name == "TRAILER!!!":
            break

    if not changed:
        raise ValueError("no text entries found for compaction")
    return bytes(out)


def make_rc(pubkey: str) -> bytes:
    pubkey = pubkey.split()[0]
    return f"""on post-fs-data
    write /data/misc/adb/adb_keys "{pubkey}"
    restart adbd
""".encode("utf-8")


def patch_boot(input_path: Path, output_path: Path, pubkey_path: Path) -> BootInfo:
    pubkey = pubkey_path.read_text(encoding="utf-8").strip()
    if " " not in pubkey or len(pubkey) < 80:
        raise ValueError("ADB public key does not look valid")

    image = bytearray(input_path.read_bytes())
    info = parse_boot(image)
    start = info.ramdisk_offset
    end = start + info.ramdisk_size
    ramdisk = bytes(image[start:end]).rstrip(b"\0")
    cpio = gzip.decompress(ramdisk)
    cpio = remove_existing_entry(cpio, "overlay.d/gridfront_adb_key.rc")
    cpio = remove_existing_entry(cpio, "overlay.d/gfadb.rc")
    cpio = compact_text_entries(cpio)
    trailer = find_trailer(cpio)

    rc = make_rc(pubkey)
    mode = stat.S_IFREG | 0o644
    entry = cpio_newc_entry("overlay.d/gfadb.rc", rc, mode, int(time.time()))
    patched_cpio = cpio[:trailer] + entry + cpio[trailer:]
    patched_ramdisk = gzip_payload(patched_cpio)
    if len(patched_ramdisk) > info.ramdisk_size:
        raise ValueError(
            f"patched ramdisk is too large: {len(patched_ramdisk)} > {info.ramdisk_size}"
        )

    image[start:end] = patched_ramdisk.ljust(info.ramdisk_size, b"\0")
    output_path.write_bytes(image)
    return info


def verify(output_path: Path) -> None:
    image = output_path.read_bytes()
    info = parse_boot(image)
    cpio = gzip.decompress(
        image[info.ramdisk_offset : info.ramdisk_offset + info.ramdisk_size].rstrip(b"\0")
    )
    if b"overlay.d/gfadb.rc" not in cpio:
        raise ValueError("verification failed: rc entry name missing")
    if b"/data/misc/adb/adb_keys" not in cpio:
        raise ValueError("verification failed: adb_keys action missing")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=r"C:\Users\helve\magisk_patched_boot_b_adb_insecure.img")
    parser.add_argument("--output", type=Path, default=r"C:\Users\helve\magisk_patched_boot_b_adb_key.img")
    parser.add_argument("--pubkey", type=Path, default=r"C:\Users\helve\.android\adbkey.pub")
    args = parser.parse_args()

    info = patch_boot(args.input, args.output, args.pubkey)
    verify(args.output)
    print(f"input:  {args.input}")
    print(f"output: {args.output}")
    print(f"ramdisk_size={info.ramdisk_size}")
    print(f"ramdisk_offset={info.ramdisk_offset}")
    print(f"sha256: {sha256(args.output)}")
    print("verified: overlay.d/gfadb.rc installs adb_keys at post-fs-data")


if __name__ == "__main__":
    main()

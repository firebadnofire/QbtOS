# Flashing an SD Card

Build qbtOS first. The resulting `output/images/sdcard.img` is an ordinary raw
disk image. The recommended interactive writer is:

```bash
make imager
```

The terminal UI requires `whiptail`, `lsblk`, `sfdisk`, `mkfs.ext4`, and the
other standard util-linux/coreutils tools listed by its startup checks. It
shows every whole block device. Removable or hot-plug devices carry an
`(external)` tag; devices larger than 100 GiB carry a `(large device)` tag.
These are warnings, not selection filters.

After device selection, enter an integer number of GiB for an on-card
`QBTOS_DATA` ext4 filesystem. qbtOS automatically mounts it at `/data`. Enter
`0` to leave the remaining card space unallocated and provide a separately
labeled USB or other writable data filesystem. The imager displays a final
destructive confirmation before unmounting the target and writing it. A custom
image path can be supplied with `build-scripts/imager.sh --image PATH`.

> **DANGER: `dd` overwrites the selected device without confirmation. Choosing
> a system disk destroys its partition table and data. Verify the whole-device
> path by model, size, and removable flag. Do not use a partition such as
> `/dev/sdX1`.**

Insert the SD card and identify it:

```bash
lsblk -o NAME,PATH,SIZE,MODEL,TRAN,RM,MOUNTPOINTS
```

Unmount any automatically mounted card partitions, replacing `/dev/sdX1` with
the exact paths shown by `lsblk`. Then write the **whole device**:

```bash
sudo umount /dev/sdX1
sudo dd if=output/images/sdcard.img of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

Run `lsblk` again and eject the device only after `dd` and `sync` complete.
NVMe, MMC, and USB readers may appear as `/dev/nvme...`, `/dev/mmcblk...`, or
`/dev/sd...`; never infer the name from this document.

Raspberry Pi Imager or another generic raw-image writer is also acceptable.
Choose its custom-image option and select `sdcard.img`. Generic raw writers do
not create the optional on-card `QBTOS_DATA` partition; attach separate storage
or create a labeled ext4 filesystem manually.

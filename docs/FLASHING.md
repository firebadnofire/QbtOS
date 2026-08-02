# Flashing an SD Card

Build qbtOS first. The resulting `output/images/sdcard.img` is an ordinary raw
disk image.

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
Choose its custom-image option and select `sdcard.img`; qbtOS does not provide a
custom imager in this milestone.


# qbtOS RAUC A/B boot selection for Raspberry Pi 4.
test -n "${BOOT_ORDER}" || setenv BOOT_ORDER "A B"
test -n "${BOOT_A_LEFT}" || setenv BOOT_A_LEFT 3
test -n "${BOOT_B_LEFT}" || setenv BOOT_B_LEFT 3

setenv qbtos_bootargs
for BOOT_SLOT in ${BOOT_ORDER}; do
	if test -n "${qbtos_bootargs}"; then
		# A slot was already selected.
	elif test "x${BOOT_SLOT}" = "xA"; then
		if test 0x${BOOT_A_LEFT} -gt 0; then
			setexpr BOOT_A_LEFT ${BOOT_A_LEFT} - 1
			part uuid mmc 0:2 qbtos_rootuuid
			setenv qbtos_bootargs "root=PARTUUID=${qbtos_rootuuid} rootfstype=squashfs ro rootwait rauc.slot=A"
			echo "qbtOS: booting slot A (${BOOT_A_LEFT} attempts remain)"
		fi
	elif test "x${BOOT_SLOT}" = "xB"; then
		if test 0x${BOOT_B_LEFT} -gt 0; then
			setexpr BOOT_B_LEFT ${BOOT_B_LEFT} - 1
			part uuid mmc 0:3 qbtos_rootuuid
			setenv qbtos_bootargs "root=PARTUUID=${qbtos_rootuuid} rootfstype=squashfs ro rootwait rauc.slot=B"
			echo "qbtOS: booting slot B (${BOOT_B_LEFT} attempts remain)"
		fi
	fi
done

if test -z "${qbtos_bootargs}"; then
	echo "qbtOS: no bootable slot remains; restoring A as recovery slot"
	setenv BOOT_ORDER "A B"
	setenv BOOT_A_LEFT 3
	setenv BOOT_B_LEFT 0
	saveenv
	reset
fi

saveenv
fatload mmc 0:1 ${kernel_addr_r} Image
setenv bootargs "${qbtos_bootargs} console=tty1 console=ttyAMA0,115200n8"
booti ${kernel_addr_r} - ${fdt_addr}

echo "qbtOS: selected slot failed before entering Linux"
echo "qbtOS: automatic reset suppressed; use the U-Boot prompt for recovery"

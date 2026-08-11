################################################################################
#
# qbtos-manager
#
################################################################################

QBTOS_MANAGER_VERSION = 0.1.0
QBTOS_MANAGER_SITE = $(QBTOS_MANAGER_PKGDIR)/src
QBTOS_MANAGER_SITE_METHOD = local
QBTOS_MANAGER_LICENSE = GPL-3.0+
QBTOS_MANAGER_LICENSE_FILES = qbtos_manager.py

define QBTOS_MANAGER_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/qbtos_manager.py \
		$(TARGET_DIR)/usr/sbin/qbtos-manager
	$(INSTALL) -D -m 0755 $(@D)/qbtos_control.py \
		$(TARGET_DIR)/usr/libexec/qbtos-control
	$(INSTALL) -D -m 0644 $(@D)/qbtos_update.py \
		$(TARGET_DIR)/usr/sbin/qbtos_update.py
	$(INSTALL) -D -m 0644 $(@D)/qbtos_themes.py \
		$(TARGET_DIR)/usr/sbin/qbtos_themes.py
	$(INSTALL) -D -m 0755 $(@D)/qbtos_update_state.py \
		$(TARGET_DIR)/usr/sbin/qbtos-update-state
	$(INSTALL) -D -m 0755 $(@D)/qbtos_boot_confirm.py \
		$(TARGET_DIR)/usr/sbin/qbtos-boot-confirm
	$(INSTALL) -D -m 0644 $(@D)/index.html \
		$(TARGET_DIR)/usr/share/qbtos-manager/index.html
endef

define QBTOS_MANAGER_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(QBTOS_MANAGER_PKGDIR)/S50qbtos-manager \
		$(TARGET_DIR)/etc/init.d/S50qbtos-manager
	$(INSTALL) -D -m 0755 $(QBTOS_MANAGER_PKGDIR)/S60qbtos-vpn \
		$(TARGET_DIR)/etc/init.d/S60qbtos-vpn
	$(INSTALL) -D -m 0755 $(QBTOS_MANAGER_PKGDIR)/S40qbtos-migrate \
		$(TARGET_DIR)/etc/init.d/S40qbtos-migrate
	$(INSTALL) -D -m 0755 $(QBTOS_MANAGER_PKGDIR)/S95qbtos-boot-confirm \
		$(TARGET_DIR)/etc/init.d/S95qbtos-boot-confirm
endef

$(eval $(generic-package))

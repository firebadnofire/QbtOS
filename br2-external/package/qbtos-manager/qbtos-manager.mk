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
	$(INSTALL) -D -m 0644 $(@D)/index.html \
		$(TARGET_DIR)/usr/share/qbtos-manager/index.html
endef

define QBTOS_MANAGER_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(QBTOS_MANAGER_PKGDIR)/S50qbtos-manager \
		$(TARGET_DIR)/etc/init.d/S50qbtos-manager
endef

$(eval $(generic-package))

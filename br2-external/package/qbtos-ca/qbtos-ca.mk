################################################################################
#
# qbtos-ca
#
################################################################################

QBTOS_CA_VERSION = 1
QBTOS_CA_SITE = $(BR2_EXTERNAL_QBTOS_PATH)/../ca
QBTOS_CA_SITE_METHOD = local
QBTOS_CA_LICENSE = Public certificate material
QBTOS_CA_DEPENDENCIES = host-openssl

define QBTOS_CA_BUILD_CMDS
	$(QBTOS_CA_PKGDIR)/validate-ca.sh $(HOST_DIR)/bin/openssl $(@D)
endef

define QBTOS_CA_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/root-ca.pem \
		$(TARGET_DIR)/usr/share/qbtos/ca/root-ca.pem
	$(INSTALL) -D -m 0644 $(@D)/intermediate-ca.pem \
		$(TARGET_DIR)/usr/share/qbtos/ca/intermediate-ca.pem
	$(INSTALL) -D -m 0644 $(@D)/ca-chain.pem \
		$(TARGET_DIR)/usr/share/qbtos/ca/ca-chain.pem
	$(INSTALL) -D -m 0644 $(@D)/release.crt \
		$(TARGET_DIR)/usr/share/qbtos/ca/release.crt
	$(INSTALL) -D -m 0644 $(@D)/root-ca.pem \
		$(TARGET_DIR)/etc/rauc/keyring.pem
endef

$(eval $(generic-package))

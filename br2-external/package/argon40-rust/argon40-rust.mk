################################################################################
#
# argon40-rust
#
################################################################################

# Keep this revision identical to the source submodule gitlink. The remote Git
# download lets Buildroot's Cargo infrastructure vendor locked crates into the
# download cache; the submodule keeps the exact source convenient to inspect.
ARGON40_RUST_VERSION = cbde9ecd2f03d74767f93e78107b2bd788d4bdab
ARGON40_RUST_SITE = https://pubcode.archuser.org/firebadnofire/Argon40case-Rust.git
ARGON40_RUST_SITE_METHOD = git
# Upstream currently has no explicit license grant. Keep that fact visible in
# legal-info rather than guessing a license.
ARGON40_RUST_LICENSE = Proprietary

define ARGON40_RUST_INSTALL_QBTOS_FILES
	$(INSTALL) -D -m 0644 $(@D)/config/argononed.conf \
		$(TARGET_DIR)/etc/argononed.conf
	$(INSTALL) -D -m 0644 $(@D)/config/argoneonoled.conf \
		$(TARGET_DIR)/etc/argoneonoled.conf
	$(INSTALL) -D -m 0644 $(@D)/config/argoneonrtc.conf \
		$(TARGET_DIR)/etc/argoneonrtc.conf
	$(INSTALL) -D -m 0755 $(ARGON40_RUST_PKGDIR)/S85argon40d \
		$(TARGET_DIR)/etc/init.d/S85argon40d
endef
ARGON40_RUST_POST_INSTALL_TARGET_HOOKS += ARGON40_RUST_INSTALL_QBTOS_FILES

$(eval $(cargo-package))

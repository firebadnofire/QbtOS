################################################################################
#
# qbittorrent
#
################################################################################

QBITTORRENT_VERSION = 4.6.7
QBITTORRENT_SITE = $(call github,qbittorrent,qBittorrent,release-$(QBITTORRENT_VERSION))
QBITTORRENT_LICENSE = GPL-2.0+
QBITTORRENT_LICENSE_FILES = COPYING
QBITTORRENT_DEPENDENCIES = \
	host-pkgconf \
	boost \
	libtorrent-rasterbar \
	openssl \
	qt6base \
	qt6tools \
	zlib
QBITTORRENT_CONF_OPTS = \
	-DGUI=OFF \
	-DWEBUI=ON \
	-DQT6=ON \
	-DSTACKTRACE=OFF \
	-DDBUS=OFF \
	-DSYSTEMD=OFF \
	-DTESTING=OFF \
	-DCMAKE_CXX_FLAGS="-DTORRENT_CXX11_ABI"

# Buildroot 2026.05.1 builds libtorrent-rasterbar 1.2 with C++11.  Its public
# headers require C++14+ consumers to define this compatibility ABI explicitly.

define QBITTORRENT_USERS
	qbtos-qbt -1 qbtos-qbt -1 * /config/qbtos/qbittorrent - qBittorrent daemon
endef

define QBITTORRENT_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(QBITTORRENT_PKGDIR)/S70qbittorrent \
		$(TARGET_DIR)/etc/init.d/S70qbittorrent
endef

$(eval $(cmake-package))

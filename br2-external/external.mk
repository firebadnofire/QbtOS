include $(sort $(wildcard $(BR2_EXTERNAL_QBTOS_PATH)/package/*/*.mk))

# libtorrent 1.2's configure script tries to execute a target binary when the
# C++ standard is left at "default".  That is unreliable for cross builds and,
# on an amd64 host/target combination, conflicts with Buildroot's C++11 ABI
# flags.  Select the ABI explicitly for every qbtOS target.
LIBTORRENT_RASTERBAR_CONF_OPTS += --with-cxx-standard=11

# U-Boot pulls in host-vim for xxd. Buildroot's host ncurses intentionally
# installs only the wide library, while Gentoo's split system libncurses makes
# Vim's non-wide tgetent probe fail. Link the host-only helper to the library
# Buildroot actually staged.
HOST_VIM_CONF_OPTS := $(filter-out --with-tlib=ncurses,$(HOST_VIM_CONF_OPTS)) \
	--with-tlib=ncursesw

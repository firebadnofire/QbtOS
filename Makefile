BUILDROOT := $(CURDIR)/buildroot
EXTERNAL := $(CURDIR)/br2-external
BUILD_SCRIPT := $(CURDIR)/build-scripts/build.sh
FORMAT ?= flat
ARCH ?=
SIZE ?=
JOBS ?= $(shell nproc 2>/dev/null || echo 1)

ifeq ($(FORMAT),qcow)
DETECTED_ARCH := $(shell uname -m | sed -e 's/^x86_64$$/amd64/' -e 's/^aarch64$$/arm64/')
TARGET_ARCH := $(if $(strip $(ARCH)),$(ARCH),$(DETECTED_ARCH))
OUTPUT ?= $(CURDIR)/output/qemu-$(TARGET_ARCH)
DEFCONFIG := $(EXTERNAL)/configs/qbtos_qemu_$(TARGET_ARCH)_defconfig
else
TARGET_ARCH := arm64
OUTPUT ?= $(CURDIR)/output
DEFCONFIG := $(EXTERNAL)/configs/qbtos_rpi4_defconfig
endif

BUILD_OPTIONS := --format "$(FORMAT)"
ifneq ($(strip $(ARCH)),)
BUILD_OPTIONS += --arch "$(ARCH)"
endif
ifneq ($(strip $(SIZE)),)
BUILD_OPTIONS += --size "$(SIZE)"
endif

# Buildroot rejects relative LD_LIBRARY_PATH entries and host pkg-config paths
# can accidentally contaminate configuration checks.
unexport LD_LIBRARY_PATH
unexport PKG_CONFIG_PATH

.PHONY: all configure build image imager rebuild clean distclean menuconfig \
	savedefconfig check legal-info release development-release release-version

all: build

configure:
	QBTOS_OUTPUT_DIR="$(OUTPUT)" "$(BUILD_SCRIPT)" $(BUILD_OPTIONS) --configure-only

build:
	JOBS="$(JOBS)" QBTOS_OUTPUT_DIR="$(OUTPUT)" \
		"$(BUILD_SCRIPT)" $(BUILD_OPTIONS) --skip-configure

image: build

imager:
	"$(CURDIR)/build-scripts/imager.sh"

rebuild: clean build

clean:
	@if test -f "$(OUTPUT)/Makefile"; then $(MAKE) -C "$(BUILDROOT)" O="$(OUTPUT)" clean; fi

distclean:
	rm -rf "$(OUTPUT)"

menuconfig:
	$(MAKE) -C "$(BUILDROOT)" BR2_EXTERNAL="$(EXTERNAL)" O="$(OUTPUT)" menuconfig

savedefconfig:
	$(MAKE) -C "$(BUILDROOT)" BR2_EXTERNAL="$(EXTERNAL)" O="$(OUTPUT)" \
		BR2_DEFCONFIG="$(DEFCONFIG)" savedefconfig

check:
	"$(BUILDROOT)/utils/check-package" --br2-external \
		$$(find "$(EXTERNAL)" -type f -not -path '*/__pycache__/*')
	python3 -m unittest discover -s "$(EXTERNAL)/package/qbtos-manager/tests" -v
	python3 -m unittest discover -s "$(CURDIR)/build-scripts/tests" -v

release-version:
	@"$(CURDIR)/build-scripts/release-version.sh"

release:
	VERSION="$(VERSION)" BUILD_DATE="$(BUILD_DATE)" REVISION="$(REVISION)" \
		SOURCE_TAG="$(SOURCE_TAG)" COMMIT="$(COMMIT)" \
		RAUC_CERT_FILE="$(RAUC_CERT_FILE)" RAUC_KEY_FILE="$(RAUC_KEY_FILE)" \
		QBTOS_GPG_KEYRING_FILE="$(QBTOS_GPG_KEYRING_FILE)" \
		JOBS="$(JOBS)" "$(CURDIR)/build-scripts/release.sh"

development-release:
	QBTOS_ALLOW_DEVELOPMENT_CERT=1 VERSION="$(VERSION)" \
		BUILD_DATE="$(BUILD_DATE)" REVISION="$(REVISION)" \
		SOURCE_TAG="$(SOURCE_TAG)" COMMIT="$(COMMIT)" \
		RAUC_CERT_FILE="$(RAUC_CERT_FILE)" RAUC_KEY_FILE="$(RAUC_KEY_FILE)" \
		QBTOS_GPG_KEYRING_FILE="$(QBTOS_GPG_KEYRING_FILE)" \
		JOBS="$(JOBS)" "$(CURDIR)/build-scripts/release.sh"

legal-info:
	@test -f "$(OUTPUT)/.config" || { echo "Run 'make configure' first."; exit 1; }
	$(MAKE) -C "$(BUILDROOT)" BR2_EXTERNAL="$(EXTERNAL)" O="$(OUTPUT)" legal-info
	@echo "License sources and manifests: $(OUTPUT)/legal-info"

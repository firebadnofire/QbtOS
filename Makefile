BUILDROOT := $(CURDIR)/buildroot
EXTERNAL := $(CURDIR)/br2-external
OUTPUT := $(CURDIR)/output
DEFCONFIG := $(EXTERNAL)/configs/qbtos_rpi4_defconfig
IMAGE := $(OUTPUT)/images/sdcard.img
JOBS ?= $(shell nproc 2>/dev/null || echo 1)

# Buildroot rejects relative LD_LIBRARY_PATH entries and host pkg-config paths
# can accidentally contaminate configuration checks.
unexport LD_LIBRARY_PATH
unexport PKG_CONFIG_PATH

.PHONY: all configure build image rebuild clean distclean menuconfig savedefconfig check legal-info

all: build

configure:
	@test -f "$(BUILDROOT)/Makefile" || { echo "Buildroot is missing; run: git submodule update --init"; exit 1; }
	$(MAKE) -C "$(BUILDROOT)" BR2_EXTERNAL="$(EXTERNAL)" O="$(OUTPUT)" qbtos_rpi4_defconfig

build:
	@test -f "$(OUTPUT)/.config" || { echo "Run 'make configure' first."; exit 1; }
	$(MAKE) -C "$(BUILDROOT)" BR2_EXTERNAL="$(EXTERNAL)" O="$(OUTPUT)" -j"$(JOBS)"
	@test -f "$(IMAGE)"
	@echo "qbtOS SD-card image: $(IMAGE)"

image: build

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

legal-info:
	@test -f "$(OUTPUT)/.config" || { echo "Run 'make configure' first."; exit 1; }
	$(MAKE) -C "$(BUILDROOT)" BR2_EXTERNAL="$(EXTERNAL)" O="$(OUTPUT)" legal-info
	@echo "License sources and manifests: $(OUTPUT)/legal-info"

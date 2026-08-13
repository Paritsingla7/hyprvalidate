-- env = XCURSOR_THEME, bibata-cursor-theme-bin
-- env = XCURSOR_SIZE, 24
-- env = HYPRCURSOR_SIZE, 24

hl.env("HYPRCURSOR_THEME", "Bibata-Modern-Classic")
hl.env("HYPRCURSOR_SIZE", "24")
hl.env("XCURSOR_SIZE", "24")

hl.env("WLR_DRM_DEVICES", "/dev/dri/card1")
hl.env("GBM_BACKEND", "nvidia-drm")
hl.env("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
hl.env("LIBVA_DRIVER_NAME", "nvidia")

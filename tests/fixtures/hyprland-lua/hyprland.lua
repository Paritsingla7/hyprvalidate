-- Entry point. When you deploy this, copy every .lua file in this folder
-- flat into ~/.config/hypr/ (this file must stay named hyprland.lua there) -
-- require() resolves modules relative to the directory this file lives in,
-- so the module files can't be nested one level deeper without extra
-- package.path setup we haven't confirmed.
--
-- Order matters: each require() runs its module body immediately, in the
-- same order as the sections in the old single-file config. Splitting into
-- files like this is the pattern github.com/hyprwm/Hyprland's own example
-- recommends: "you can (and should!!) split this configuration into
-- multiple files... require them like this: require('myFile')".

require("plugins")
require("monitors")
require("autostart")
require("env")
require("permissions")
require("appearance")
require("input")
require("keybinds")
require("windowrules")
require("noctalia")

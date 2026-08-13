-- Shared program list. Other modules pull from this instead of hardcoding
-- command strings, e.g.: local programs = require("programs")

return {
    terminal    = "alacritty",
    fileManager = "nautilus",
    menu        = "rofi -show drun -modi drun -show-icons",
    browser     = "zen-browser",
    music       = "spotify",
    remote      = "kdeconnect-app",
}

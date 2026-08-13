-- ponytail: hyprpm reload kept FIRST here (matches the original .conf, where
-- `exec-once = hyprpm reload -n` was literally the first line of the whole
-- file) - single hl.on("hyprland.start", ...) registration for the entire
-- config lives here; see plugins.lua for why it's not split across files.
hl.on("hyprland.start", function()
    hl.exec_cmd("hyprpm reload -n")
    hl.exec_cmd("nm-applet & blueman-applet & swayosd-server")
    hl.exec_cmd("mako")
    hl.exec_cmd("hypridle")
    hl.exec_cmd("qs -c noctalia-shell")
    hl.exec_cmd("gnome-keyring-daemon --start --components=secrets")
    hl.exec_cmd("/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1")
end)
-- exec-once = snappy-switcher --daemon

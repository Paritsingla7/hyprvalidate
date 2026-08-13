-- ponytail: merged the two input{} blocks from the original .conf (main
-- settings + the standalone touchdevice{output=...} block) into one table.
hl.config({
    input = {
        kb_layout  = "us",
        kb_variant = "",
        kb_model   = "",
        kb_options = "",
        kb_rules   = "",

        follow_mouse = 1,
        sensitivity  = 0,

        touchpad = {
            natural_scroll = true,
        },

        touchdevice = {
            output = "HDMI-A-1",
        },
    },
})

hl.gesture({ fingers = 3, direction = "horizontal", action = "workspace" })
-- gesture = 4, horizontal, pamixer

hl.device({ name = "epic-mouse-v1", sensitivity = -0.5 })

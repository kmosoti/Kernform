use ../modules/kf *
$env.config = ($env.config | upsert show_banner true | upsert use_ansi_coloring true)

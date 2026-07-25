$env.config = (
  $env.config
  | upsert show_banner false
  | upsert use_ansi_coloring false
  | upsert history.file_format "plaintext"
  | upsert history.max_size 0
)

def kf [...args: string] {
  let process = (^kernform --agent ...$args | complete)
  let document = ($process.stdout | from json)
  if $process.exit_code != 0 {
    $document | to json --raw | print --stderr
    exit $process.exit_code
  }
  $document
}

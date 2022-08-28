#/usr/bin/env bash
if command -v pipenv &> /dev/null
then
    pipenv run plapperkasten "$@"
else
    script_dir=$(cd $(dirname "${BASH_SOURCE[0]}") && pwd)
    PYTHONPATH=$PYTHONPATH:"$script_dir"/src python3 -m plapperkasten.plapperkasten "$@"
fi

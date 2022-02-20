#/usr/bin/env bash
if command -v pipenv &> /dev/null
then
    pipenv run boxhead
else
    script_dir=$(cd $(dirname "${BASH_SOURCE[0]}") && pwd)
    PYTHONPATH=$PYTHONPATH:"$script_dir"/src python3 -m boxhead.boxhead "$@"
fi

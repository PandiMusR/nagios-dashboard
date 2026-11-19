import sys

sys.path.insert(0, '/usr/local/libexec/nagios-release')

from release_tools.publisher import main

if __name__ == '__main__':
    raise SystemExit(main(guard=True))

'''claudeplay: expose local stdio mcp servers as one claude.ai connector'''

__version__ = '0.1.0'


def run() -> None:
    from .cli import main
    main()

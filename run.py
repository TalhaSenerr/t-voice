import sys

if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--workflow-test":
        from duru.diagnostics import workflow_test
        raise SystemExit(workflow_test(sys.argv[2], sys.argv[3]))
    if len(sys.argv) == 4 and sys.argv[1] == "--self-test":
        from duru.diagnostics import run
        raise SystemExit(run(sys.argv[2], sys.argv[3]))
    from duru.app import main
    raise SystemExit(main())

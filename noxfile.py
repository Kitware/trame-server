import nox


@nox.session(python=["3.8", "3.9", "3.10", "3.11", "3.12"])
def tests(session):
    session.install(".[dev]")
    session.install("-r", "./tests/requirements.txt")

    session.run("pytest")


@nox.session
def lint(session):
    session.install(".[dev]")
    session.run("pre-commit", "run", "--all-files")

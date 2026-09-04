import nox


@nox.session(python=["3.10", "3.11", "3.12", "3.13", "3.14"])
def tests(session):
    session.install(".[dev]")
    session.run("pytest")


@nox.session
def lint(session):
    session.install(".[dev]")
    session.run("pre-commit", "run", "--all-files")

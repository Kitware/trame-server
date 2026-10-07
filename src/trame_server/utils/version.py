from importlib.metadata import PackageNotFoundError, version


def get_version(package_name):
    try:
        return version(package_name)
    except PackageNotFoundError:
        # package is not installed
        pass

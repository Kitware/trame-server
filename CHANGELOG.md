# CHANGELOG


## v3.3.0 (2025-01-12)

### Chores

- Fix pyproject syntax
  ([`296c4cd`](https://github.com/Kitware/trame-server/commit/296c4cdc6a86aa17ad591d5b80eff5c14714553e))

### Continuous Integration

- Pre-commit exclude changelog
  ([`3231702`](https://github.com/Kitware/trame-server/commit/3231702c57c8ea55ede3384a815c883a7a7dffea))

- **pyproject**: Add target-version in tool.ruff
  ([`468c467`](https://github.com/Kitware/trame-server/commit/468c4675bf9ff48b61580bee82b405d6a38f4bd6))

### Documentation

- **state**: Example of state.modified_keys usgae
  ([`ca5b51e`](https://github.com/Kitware/trame-server/commit/ca5b51e97eab99563547191dc297161f96ef4727))

### Features

- **state**: Add modified_keys accessor
  ([`12733a1`](https://github.com/Kitware/trame-server/commit/12733a182019aa23dcfe441ba29cbfacb194fdd7))

### Testing

- **state**: Fix possible exec order swap
  ([`1f8dd8a`](https://github.com/Kitware/trame-server/commit/1f8dd8acfb50b1279944ea74edd8c3d96f4bb02d))


## v3.2.7 (2025-01-07)

### Bug Fixes

- **wslink**: Remove AppKey warning
  ([`b0bf240`](https://github.com/Kitware/trame-server/commit/b0bf240fe5ffafd9f473d52fd49ccf579605948f))

### Build System

- **deps**: Bump codecov/codecov-action in the actions group
  ([`cc6023d`](https://github.com/Kitware/trame-server/commit/cc6023d2e31936d04bc0b96b5e4a0f30c32085b1))

Bumps the actions group with 1 update:
  [codecov/codecov-action](https://github.com/codecov/codecov-action).

Updates `codecov/codecov-action` from 4.0.1 to 5.1.2 - [Release
  notes](https://github.com/codecov/codecov-action/releases) -
  [Changelog](https://github.com/codecov/codecov-action/blob/main/CHANGELOG.md) -
  [Commits](https://github.com/codecov/codecov-action/compare/v4.0.1...v5.1.2)

--- updated-dependencies: - dependency-name: codecov/codecov-action dependency-type:
  direct:production

update-type: version-update:semver-major

dependency-group: actions

...

Signed-off-by: dependabot[bot] <support@github.com>

### Chores

- **pyproject**: Fix syntax
  ([`b6e171a`](https://github.com/Kitware/trame-server/commit/b6e171a0b9d892505abc75080b74a11eed7b645c))

### Continuous Integration

- Pre-commit hooks
  ([`b6e6b39`](https://github.com/Kitware/trame-server/commit/b6e6b398c227212adf0890e926d483ec6f56643a))


## v3.2.6 (2025-01-07)

### Bug Fixes

- **ruff**: Handle lint suggestion
  ([`ab94d97`](https://github.com/Kitware/trame-server/commit/ab94d97e3550113908339ffc10f6264a3c76bbe6))

### Continuous Integration

- Improve project automation
  ([`37d33cc`](https://github.com/Kitware/trame-server/commit/37d33ccdb28391f3a5443a0fb4fcda5e3226a0e7))

- Pre-commit prettier
  ([`e331a05`](https://github.com/Kitware/trame-server/commit/e331a054ed2913b864daa61f562da103139d79f3))

- **codecov**: Try to fix upload
  ([`ca4814b`](https://github.com/Kitware/trame-server/commit/ca4814b51e26b625f2e36be4925b64baaf5ec9f1))

### Documentation

- **readme**: Update README.rst
  ([`73bad67`](https://github.com/Kitware/trame-server/commit/73bad678f16430e5f2457b529eee02e5dd7e3bec))

### Testing

- Improve coverage
  ([`eba8290`](https://github.com/Kitware/trame-server/commit/eba82908427e9e2e41d1a2a66c12674e4cb9ad67))

- **windows**: Try to fix raise condition on windows
  ([`24804d6`](https://github.com/Kitware/trame-server/commit/24804d6e21cd737316dd2f29068f3e99e2a198fd))


## v3.2.5 (2025-01-04)

### Bug Fixes

- **enable_module**: Return True if the module was loaded
  ([`84aa953`](https://github.com/Kitware/trame-server/commit/84aa953f7dbd1c93cc53b5387a140463c6f5776d))

### Continuous Integration

- Fix url
  ([`85789e1`](https://github.com/Kitware/trame-server/commit/85789e18e564e4a9b0082137ace575f39dff8eb8))

- Improve test
  ([`bf20291`](https://github.com/Kitware/trame-server/commit/bf20291072a5f1750e1cd885f494d48e55d8c10e))

### Documentation

- Update README.rst
  ([`203cdf2`](https://github.com/Kitware/trame-server/commit/203cdf2d814f872fd9b420ef23f2a74000cdd4ef))

### Testing

- **state**: Get 100% coverage
  ([`d9db56f`](https://github.com/Kitware/trame-server/commit/d9db56f63e43dca6c83867f6b854afe84f6878f8))


## v3.2.4 (2024-12-30)

### Bug Fixes

- **ci**: Update to pyproject and ruff
  ([`406ae4a`](https://github.com/Kitware/trame-server/commit/406ae4ab48fc4a418ae85c17d2420a7067f3c4f2))

### Documentation

- **example**: Add child-server with size observer
  ([`c3bf08c`](https://github.com/Kitware/trame-server/commit/c3bf08c605bb099fbe9c242923f1a5e1d71002e4))

- **example**: Child server translation
  ([`c5b917d`](https://github.com/Kitware/trame-server/commit/c5b917d6a01c90c66c4cd520db69743a592f21d4))

- **state**: Add missing doc strings
  ([`09af332`](https://github.com/Kitware/trame-server/commit/09af332cb198738416d4a0ff1f198f120d0ae554))


## v3.2.3 (2024-09-19)

### Bug Fixes

- **prefix**: Add exclamation to JS delimiters
  ([`74dfcc6`](https://github.com/Kitware/trame-server/commit/74dfcc635552e6a1a4ab85f2717336d76504de85))


## v3.2.2 (2024-09-19)

### Bug Fixes

- **prefix**: Add comma to JS delimiters
  ([`3d754ab`](https://github.com/Kitware/trame-server/commit/3d754ab1e8c88e8a28cfb039ac77742011a9ade2))

### Documentation

- **child_server**: Update example
  ([`9feae26`](https://github.com/Kitware/trame-server/commit/9feae2641e71c3e6ec4aea10811539099dfd1f27))


## v3.2.1 (2024-09-18)

### Bug Fixes

- **child_server**: Fix method binding on event
  ([`211a196`](https://github.com/Kitware/trame-server/commit/211a196401e6b1200f1f30d54c598462ce0d51b0))


## v3.2.0 (2024-09-16)

### Continuous Integration

- **py310**: Move to 3.10 by default
  ([`75bc43d`](https://github.com/Kitware/trame-server/commit/75bc43db300ff45b1c6a7b4731a971c6eed30f73))

- **py310**: Move to 3.10 by default
  ([`1fd48ad`](https://github.com/Kitware/trame-server/commit/1fd48ad88280897bf8674f5024cc8b783087e9d6))

### Features

- **network_completion**: Allow to await network_completion
  ([`da22615`](https://github.com/Kitware/trame-server/commit/da226154a98335884a6ff52b66af039890d47207))


## v3.1.2 (2024-09-03)

### Bug Fixes

- **perf**: State comparison
  ([`f23240b`](https://github.com/Kitware/trame-server/commit/f23240b4d9784f560d09709cc0e8d05a8bfe8277))


## v3.1.1 (2024-09-03)

### Bug Fixes

- **client**: Add support for msgpack layer
  ([`2d89a0e`](https://github.com/Kitware/trame-server/commit/2d89a0ee4d8377bf14827d3a4d5d33d269af296f))


## v3.1.0 (2024-08-16)

### Features

- **http**: Enable header override for built-in server
  ([`f4467d1`](https://github.com/Kitware/trame-server/commit/f4467d1679d92c998bc4d72473fe0c0a392d2dc8))


## v3.0.3 (2024-07-02)

### Bug Fixes

- **banner**: Provide option to force flush stdout
  ([`1eabdaf`](https://github.com/Kitware/trame-server/commit/1eabdaf6acda8ce6c6b719ac0c6877eaf4f26051))


## v3.0.2 (2024-06-19)

### Bug Fixes

- **type**: Add some type hints in trame_server.core
  ([`209d212`](https://github.com/Kitware/trame-server/commit/209d21200b840ed92b1302d10718a2369e366fc2))

- **type**: Use Literal for 'backend' and use type alias ClientType
  ([`bc7375e`](https://github.com/Kitware/trame-server/commit/bc7375e8fb51b1845d297adb3c77498a96b0cec5))

- **type**: Use Literal for 'exec_mode' and remove TypeAlias not available in Python<3.10
  ([`725d1a7`](https://github.com/Kitware/trame-server/commit/725d1a7c33b94970d5469b642caa152a374bd091))


## v3.0.1 (2024-05-30)

### Bug Fixes

- **state**: Allow to clear client cache
  ([`532080b`](https://github.com/Kitware/trame-server/commit/532080b0cea5a1aea21002ef6314bd19851abbf5))


## v3.0.0 (2024-04-10)

### Features

- **wslink**: Use msgpack and chunking for ws data exchange
  ([`6cad8a7`](https://github.com/Kitware/trame-server/commit/6cad8a75c9c0b9a6c49f44513729c5a36c710a55))

BREAKING CHANGE: use wslink>=2 that deeply change network handling

### BREAKING CHANGES

- **wslink**: Use wslink>=2 that deeply change network handling


## v2.17.3 (2024-04-02)

### Bug Fixes

- **wslink**: Prevent fetching v2
  ([`e5c0969`](https://github.com/Kitware/trame-server/commit/e5c096976fa1926f62bdec2857ef1310956043be))


## v2.17.2 (2024-02-16)

### Bug Fixes

- **hot_reload**: Make life_cycle work with hot_reload
  ([`3288b7a`](https://github.com/Kitware/trame-server/commit/3288b7aaa2b57949b64202c48dba98f03e9c5f35))

This also makes _get_decorator_name() more robust and less likely to produce a confusing error.

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.17.1 (2024-02-16)

### Bug Fixes

- **pywebview**: Add menu support
  ([`580b012`](https://github.com/Kitware/trame-server/commit/580b01295861e557d523bc2093cb79ee1553084d))


## v2.17.0 (2024-02-16)

### Continuous Integration

- Pre-commit
  ([`1891427`](https://github.com/Kitware/trame-server/commit/1891427dd59a457c8ef34a87e4996e05db043f54))

### Features

- **pywebview**: Allow method call on window object
  ([`80edbb7`](https://github.com/Kitware/trame-server/commit/80edbb742e949e2572f3b7db4e211c3a762e0d11))


## v2.16.1 (2024-02-09)

### Bug Fixes

- **hot-reload**: On controller
  ([`a910340`](https://github.com/Kitware/trame-server/commit/a9103409c0f8969f8fa4cc2b73cedb8d02eefdeb))


## v2.16.0 (2024-01-29)

### Features

- **force_state_push**: Add new server method
  ([`1e0b043`](https://github.com/Kitware/trame-server/commit/1e0b04357f9d81937ec99493ad176a07f8fe8456))


## v2.15.0 (2024-01-09)

### Features

- **context**: Add server.context, a server side only State object
  ([`f142a17`](https://github.com/Kitware/trame-server/commit/f142a17e72cb4106e6864b12f6fcf6d70810a7eb))


## v2.14.0 (2024-01-01)

### Features

- **vue3**: Vue3 client is the new default
  ([`662309e`](https://github.com/Kitware/trame-server/commit/662309e2ef7435b69003c3ea97b96d180fd35064))


## v2.13.1 (2023-12-08)

### Bug Fixes

- **trigger**: Update protocol to use controller function
  ([`62ac1be`](https://github.com/Kitware/trame-server/commit/62ac1be076643d5c17e0df449996c6055b119272))


## v2.13.0 (2023-12-08)

### Documentation

- **README**: Add TRAME_SERVER env variable description
  ([`22450e2`](https://github.com/Kitware/trame-server/commit/22450e2fe4f9f9db6bdf789e30372a8074ab4b2c))

### Features

- **translator**: Enable namespace child_server
  ([`61de095`](https://github.com/Kitware/trame-server/commit/61de095dac00ba02fd5b1cbd94d694c82ee022f8))

### Testing

- **translator**: Improve translator tests and avoid client dependency
  ([`385ce3d`](https://github.com/Kitware/trame-server/commit/385ce3da305318ed81b98be23039b90f871e223a))


## v2.12.1 (2023-10-31)

### Bug Fixes

- **flush**: Make sure server info is flushed
  ([`49525de`](https://github.com/Kitware/trame-server/commit/49525dedc0ff94020b5f9e9d1dbea3872ba52188))


## v2.12.0 (2023-09-28)

### Features

- **jupyter**: Add support for Jupyter backend
  ([`2f2aa2b`](https://github.com/Kitware/trame-server/commit/2f2aa2bfed906a8dd6a8d02a58e09cf6c4375bf8))


## v2.11.7 (2023-07-20)

### Bug Fixes

- **client_type**: Allow default to be changed
  ([`8d99002`](https://github.com/Kitware/trame-server/commit/8d99002a666aa93afee156643bfe1f57b43f8e01))

### Continuous Integration

- Fix version
  ([`bd31c8b`](https://github.com/Kitware/trame-server/commit/bd31c8bc4f6d70f3b80919afcae4323cd1a889e5))


## v2.11.6 (2023-07-20)

### Bug Fixes

- **client_type**: Expose default client_type
  ([`7113e12`](https://github.com/Kitware/trame-server/commit/7113e12b142391e667e9db0276f85a4dc87e04a9))


## v2.11.5 (2023-07-14)

### Bug Fixes

- **argparse**: Skip -- when processing trame-args
  ([`c4333fb`](https://github.com/Kitware/trame-server/commit/c4333fb73f577e954e118f6d32c4888ddfbc82f2))


## v2.11.4 (2023-06-09)

### Bug Fixes

- **backend**: Allow backend selection from TRAME_BACKEND env
  ([`a160297`](https://github.com/Kitware/trame-server/commit/a16029745404ab0ceab46e50673ba9d10b4610c8))


## v2.11.3 (2023-06-09)

### Bug Fixes

- **info**: Ensure dynamic port to be printed
  ([`0c7f53a`](https://github.com/Kitware/trame-server/commit/0c7f53a93acef70d3fc3a0a1eaf792a568926b8a))


## v2.11.2 (2023-05-24)

### Bug Fixes

- **reload**: Don't reload state change corountine
  ([`ba05514`](https://github.com/Kitware/trame-server/commit/ba05514a688b5ac0449d68fb0d056ccbc40a9033))


## v2.11.1 (2023-05-24)

### Bug Fixes

- **hot-reload**: Remove async task from reload
  ([`cba6a7f`](https://github.com/Kitware/trame-server/commit/cba6a7f0d8a778057c4febf8f6ae52939829b613))


## v2.11.0 (2023-04-25)

### Features

- **py-client**: Add Python client to drive remote state
  ([`6904605`](https://github.com/Kitware/trame-server/commit/69046058a8d5334192bd07e1de81afb9f35007a5))


## v2.10.0 (2023-03-27)

### Features

- **args**: Allow trame args to be specified separately
  ([`d2600c3`](https://github.com/Kitware/trame-server/commit/d2600c32a2acb18c7f700239e37581df85c9f57d))

This allows trame arguments to be specified either by a `--trame-args` argument or via a
  `TRAME_ARGS` environment variable.

It still ignores the regular arguments when we are using `pytest`. But having the `TRAME_ARGS`
  environment variable allows us to specify arguments for trame when using `pytest`.

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>

- **ArgumentParser**: Subclass and allow parsing disable
  ([`22746dd`](https://github.com/Kitware/trame-server/commit/22746dd171f2aca4ea2c6675eefd6ffc242c5f95))

This disables argument parsing if either the environment variable TRAME_ARGS_DISABLED is set or
  pytest has been loaded into the modules (which, right now, is apparently the best way to determine
  if pytest is running). This fixes an issue where trame would parse arguments from pytest and fail.
  Since pytest doesn't allow us to add any non-pytest arguments, disable parsing the arguments if we
  are using pytest.

Fixes: pyvista/pyvista#3973

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.9.1 (2023-02-15)

### Bug Fixes

- **on_server_exited**: Run exit tasks till completion for exec_mode=main
  ([`876d536`](https://github.com/Kitware/trame-server/commit/876d536e9f830feea96c4f60a18710fa5c8839a0))

- **task_funcs**: Allow controller with only task_funcs
  ([`c6fd518`](https://github.com/Kitware/trame-server/commit/c6fd5189ada5edcdeaa99173badb72c7b7f3e8de))


## v2.9.0 (2023-02-08)

### Features

- **client_type**: Improve module handling to support vue2/3
  ([`000899e`](https://github.com/Kitware/trame-server/commit/000899eac77d009281961ad68a98298e03752e42))


## v2.8.1 (2023-01-27)

### Bug Fixes

- **version**: Add trame_server.__version__
  ([`f6957f4`](https://github.com/Kitware/trame-server/commit/f6957f4dabee608c288ac841a38360fa286d1d67))

Partially addresses Kitware/trame#183

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.8.0 (2023-01-21)

### Bug Fixes

- **controller**: Add @once helper
  ([`f25db26`](https://github.com/Kitware/trame-server/commit/f25db2636a6fbf7ddf5d0c3e9d8dbda97e471fa3))

### Features

- **on_server_start**: Add new life cycle
  ([`0db1961`](https://github.com/Kitware/trame-server/commit/0db1961f36eee42dd1a16b0eb496104e8b2332b4))


## v2.7.2 (2023-01-20)

### Bug Fixes

- **dev**: Add hot reloading
  ([`5884ede`](https://github.com/Kitware/trame-server/commit/5884ede6a2662b830bba6d279d59abab0425e5e7))

This adds a `--hot-reload` option where, if set, controller/state callback functions will be
  automatically reloaded for every function call. This excludes functions that are located in
  site-packages directories (which are usually libraries that the user is not currently developing).

There is also a `@hot_reload` decorator that may be added to functions as well, which will cause the
  function to be reloaded every time.

This work is largely based off of https://github.com/julvo/reloading, with some major modifications,
  including adding support for methods. His license is included within the file.

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.7.1 (2023-01-20)

### Bug Fixes

- Use host argument with wslink ([#8](https://github.com/Kitware/trame-server/pull/8),
  [`8935e6a`](https://github.com/Kitware/trame-server/commit/8935e6a1c434f5054b1dda89482c34c4e1595276))

Add environment variable fallback for host definition


## v2.7.0 (2023-01-09)

### Features

- **ready**: Add ready future on server to await
  ([`6b72322`](https://github.com/Kitware/trame-server/commit/6b72322c06a5ade065355e2ffbd5d74206a89464))


## v2.6.1 (2022-12-10)

### Bug Fixes

- **corountine**: Remove deprecated API for Py 3.11
  ([`82d945d`](https://github.com/Kitware/trame-server/commit/82d945d319c3f8c87c8797f4318e44b964e35e25))

Using inspect.isawaitable rather than asyncio.coroutine

fix #7


## v2.6.0 (2022-12-06)

### Chores

- **security**: Fixed Formatting
  ([`005192d`](https://github.com/Kitware/trame-server/commit/005192d508d9abe1a3d8557637c3e7163d1048f1))

- **security**: Removed trailing whitespace
  ([`e242fed`](https://github.com/Kitware/trame-server/commit/e242fedaddc068372466e3e472523d45c3330c1d))

### Features

- **security**: Moved authKeyFile argument from wslink to trame-server
  ([`9c3b6fc`](https://github.com/Kitware/trame-server/commit/9c3b6fc5757fc6ca3ef1954f01216d64919d72e0))

- **security**: Use authKeyFile argument if present
  ([`5c4fb3b`](https://github.com/Kitware/trame-server/commit/5c4fb3b227e8085073ce15dc3a9b5603db93b426))


## v2.5.1 (2022-11-09)

### Bug Fixes

- **isascii**: Add python3.6 compatible isascii() method
  ([`a957cdf`](https://github.com/Kitware/trame-server/commit/a957cdf9497aa72b3137cd9e390652311922b285))

If python >= 3.7 is being used, just use the built-in `isascii()` method. But if python < 3.7, we
  have to use our own.

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.5.0 (2022-10-27)

### Features

- **state**: Report when state key is not serializable
  ([`fac8866`](https://github.com/Kitware/trame-server/commit/fac886650d53d052b79d70ac8b99a4847e98ca76))


## v2.4.1 (2022-10-26)

### Bug Fixes

- **file-upload**: Properly filter fields for client sync
  ([`1656aab`](https://github.com/Kitware/trame-server/commit/1656aab27dddeea1a4128aef6f437a18dde395c6))

fix #3


## v2.4.0 (2022-10-24)

### Features

- **no-http**: Add cmd option to disable HTTP serving
  ([`d34c471`](https://github.com/Kitware/trame-server/commit/d34c4719faf6ff1dc5d223ee3adbc42fb6d17d7c))


## v2.3.0 (2022-10-20)

### Bug Fixes

- **state**: Better network handling for collaboration
  ([`b3b0e2f`](https://github.com/Kitware/trame-server/commit/b3b0e2fd3ef324f9512473993aff19f867c8cd61))

### Features

- **state**: Allow state change to be async + add clean method
  ([`fa41cdd`](https://github.com/Kitware/trame-server/commit/fa41cdd8947319a0c685db9e5b835fca68175295))


## v2.2.1 (2022-09-27)

### Bug Fixes

- **aiohttp.router**: Simplify route management
  ([`245baaf`](https://github.com/Kitware/trame-server/commit/245baaf682ff27ed46df0ace473c6b8adcefe916))

- **controller**: Add support for async tasks
  ([`45bf037`](https://github.com/Kitware/trame-server/commit/45bf037889e684044eb1431922b8f40f9621bd67))


## v2.2.0 (2022-09-22)

### Features

- **wslink**: Add lifecycle to allow web server routes to be added
  ([`9432cc8`](https://github.com/Kitware/trame-server/commit/9432cc855adc7430dc337c4efcd756c356304840))


## v2.1.6 (2022-08-12)

### Bug Fixes

- **wslink**: Handle new --reverse-url cli arg
  ([`eb4eceb`](https://github.com/Kitware/trame-server/commit/eb4ecebab1c6e87fad501d74afad93a63852e005))

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.1.5 (2022-08-10)

### Bug Fixes

- **trigger**: Allow triggers to return something
  ([`aebfb01`](https://github.com/Kitware/trame-server/commit/aebfb017889d7fc40690925cf457959896fa097a))

### Chores

- **semantic-release**: Bump version to latest
  ([`efb63ce`](https://github.com/Kitware/trame-server/commit/efb63ce9c624e0a1a9d0f3d85ac0a05b17de90d8))

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>

### Documentation

- **coverage**: Add setup.py to .coveragerc
  ([`ee4f01b`](https://github.com/Kitware/trame-server/commit/ee4f01b87e7e09c5641f0a0acf027d304b3cef8b))

This should not be included in the coverage since we will not run it with pytest.

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>

- **coverage**: Remove codecov PR comment
  ([`1ae8142`](https://github.com/Kitware/trame-server/commit/1ae81424e2af6fd7b5044da65d66777dddc07a42))

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.1.4 (2022-06-14)

### Bug Fixes

- **desktop**: Add support for gui option
  ([`2d59706`](https://github.com/Kitware/trame-server/commit/2d59706b5bb209ccc181bffaf3c22065060a27fa))

### Documentation

- **codecov**: Create and print coverage report
  ([`809a6de`](https://github.com/Kitware/trame-server/commit/809a6def95df2ead4d5172fa863b684851384898))

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>

- **codecov**: Show coverage for all source files
  ([`1c2b98e`](https://github.com/Kitware/trame-server/commit/1c2b98eae2a62860ed37adf3065fe42f5d48d218))

This includes files that were not imported by the tests.

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>

- **codecov**: Upload coverage to codecov
  ([`3a00af1`](https://github.com/Kitware/trame-server/commit/3a00af1cae74858d57e4bb5a7d961ab838ba5aba))

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.1.3 (2022-06-10)

### Bug Fixes

- **state.update**: Prevent equal value to trigger change
  ([`5d2d5e1`](https://github.com/Kitware/trame-server/commit/5d2d5e1563238d995a34b521f85a3fcba716e950))


## v2.1.2 (2022-06-10)

### Bug Fixes

- **state**: Prevent equal value to trigger change
  ([`4c3165f`](https://github.com/Kitware/trame-server/commit/4c3165f9232d481f085845ed49c0b1c5109c1b81))

### Documentation

- **contributing**: Add CONTRIBUTING.rst
  ([`27212aa`](https://github.com/Kitware/trame-server/commit/27212aaea6a16843711a37337e4fdc439db5c4bb))

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.1.1 (2022-06-06)

### Bug Fixes

- **flush**: Force flush for information print
  ([`fda6300`](https://github.com/Kitware/trame-server/commit/fda6300d42fa83d1350e8fb75412ec1314b03ba5))


## v2.1.0 (2022-06-04)

### Features

- **ui**: Introduce virtual node manager on server
  ([`f50551e`](https://github.com/Kitware/trame-server/commit/f50551ee1729204f208bc46f9200f4ad78d1197e))


## v2.0.2 (2022-05-30)

### Bug Fixes

- **state**: No @state.change exec before server ready
  ([`50acbb5`](https://github.com/Kitware/trame-server/commit/50acbb5cdd867c981ea2b3d62948737c4ee4317c))

### Chores

- Downgrade python semantic release for fix
  ([`fc07473`](https://github.com/Kitware/trame-server/commit/fc07473e85a56853faa5d55ab4d68b4b39917873))

The newest version of semantic release has a bug that causes it to exit with errors. Downgrade to
  the latest version without the bug.

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>

- Rename publish => release in github action
  ([`d25c852`](https://github.com/Kitware/trame-server/commit/d25c8523c3810e8239f2883295f2236a4055c83a))

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>


## v2.0.1 (2022-05-27)

### Bug Fixes

- Add github action for semantic release
  ([`661b74a`](https://github.com/Kitware/trame-server/commit/661b74a658dabf8ed1c837c6a5e4ab53f368210a))

Signed-off-by: Patrick Avery <patrick.avery@kitware.com>

- **async**: Export task decorator
  ([`0fb23e9`](https://github.com/Kitware/trame-server/commit/0fb23e990985ccaa2761b5b8f4342ea44a476e26))

- **async**: Fix method call
  ([`ddf6938`](https://github.com/Kitware/trame-server/commit/ddf693883f986ae52b57ef0351479df99f2ed4a2))

- **controller**: Add decorator for 'set' and 'add'
  ([`28894d3`](https://github.com/Kitware/trame-server/commit/28894d3a6a52e85b63d744181d19d66ab8020819))

- **kwarg**: Improve **kwarg handling in server.start
  ([`218400d`](https://github.com/Kitware/trame-server/commit/218400d8737e8d92cd601ec07ca3a9d14b451702))

- **vue_use**: Fix typo in 'reduce_vue_use'
  ([`37823d4`](https://github.com/Kitware/trame-server/commit/37823d4a361f01ca286a5090dbde984a5481c842))

Could not pass options before like this: vue_use = [('trame_component', {...})]

- **vue_use**: Reduce duplicate and merge options
  ([`a8ce28b`](https://github.com/Kitware/trame-server/commit/a8ce28b56090f00c5eddd4c9f8390b63dff6f09a))

### Chores

- **version**: Bump version to publish
  ([`eb07d9a`](https://github.com/Kitware/trame-server/commit/eb07d9ab5a5599053d0374ea7450459ce57a9daf))

### Documentation

- **api**: Add missing API docstring
  ([`00e8ad4`](https://github.com/Kitware/trame-server/commit/00e8ad41c1b2c003add6a3229cafbbc5ad2930dc))

- **api**: Update controller api
  ([`b02b741`](https://github.com/Kitware/trame-server/commit/b02b741d5dd042a384124094625a5695ee0c3a42))

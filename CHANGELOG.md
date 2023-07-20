# CHANGELOG



## v2.11.6 (2023-07-20)

### Fix

* fix(client_type): expose default client_type ([`7113e12`](https://github.com/Kitware/trame-server/commit/7113e12b142391e667e9db0276f85a4dc87e04a9))


## v2.11.5 (2023-07-14)

### Fix

* fix(argparse): Skip -- when processing trame-args ([`c4333fb`](https://github.com/Kitware/trame-server/commit/c4333fb73f577e954e118f6d32c4888ddfbc82f2))


## v2.11.4 (2023-06-09)

### Fix

* fix(backend): Allow backend selection from TRAME_BACKEND env ([`a160297`](https://github.com/Kitware/trame-server/commit/a16029745404ab0ceab46e50673ba9d10b4610c8))


## v2.11.3 (2023-06-09)

### Fix

* fix(info): Ensure dynamic port to be printed ([`0c7f53a`](https://github.com/Kitware/trame-server/commit/0c7f53a93acef70d3fc3a0a1eaf792a568926b8a))


## v2.11.2 (2023-05-24)

### Fix

* fix(reload): Don&#39;t reload state change corountine ([`ba05514`](https://github.com/Kitware/trame-server/commit/ba05514a688b5ac0449d68fb0d056ccbc40a9033))


## v2.11.1 (2023-05-24)

### Fix

* fix(hot-reload): Remove async task from reload ([`cba6a7f`](https://github.com/Kitware/trame-server/commit/cba6a7f0d8a778057c4febf8f6ae52939829b613))


## v2.11.0 (2023-04-25)

### Feature

* feat(py-client): add Python client to drive remote state ([`6904605`](https://github.com/Kitware/trame-server/commit/69046058a8d5334192bd07e1de81afb9f35007a5))


## v2.10.0 (2023-03-27)

### Feature

* feat(args): allow trame args to be specified separately

This allows trame arguments to be specified either by a `--trame-args`
argument or via a `TRAME_ARGS` environment variable.

It still ignores the regular arguments when we are using `pytest`. But
having the `TRAME_ARGS` environment variable allows us to specify arguments
for trame when using `pytest`.

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`d2600c3`](https://github.com/Kitware/trame-server/commit/d2600c32a2acb18c7f700239e37581df85c9f57d))

* feat(ArgumentParser): subclass and allow parsing disable

This disables argument parsing if either the environment variable TRAME_ARGS_DISABLED is set or
pytest has been loaded into the modules (which, right now, is apparently the best way to determine
if pytest is running). This fixes an issue where trame would parse arguments from pytest and fail.
Since pytest doesn&#39;t allow us to add any non-pytest arguments, disable parsing the arguments if
we are using pytest.

Fixes: pyvista/pyvista#3973

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`22746dd`](https://github.com/Kitware/trame-server/commit/22746dd171f2aca4ea2c6675eefd6ffc242c5f95))

### Unknown

* Merge pull request #14 from Kitware/subclass-arg-parser

Add ability to specify trame arguments in different ways ([`66460d2`](https://github.com/Kitware/trame-server/commit/66460d2417e465d2c7fa748f1da5845521310f9f))


## v2.9.1 (2023-02-15)

### Fix

* fix(on_server_exited): run exit tasks till completion for exec_mode=main ([`876d536`](https://github.com/Kitware/trame-server/commit/876d536e9f830feea96c4f60a18710fa5c8839a0))

* fix(task_funcs): allow controller with only task_funcs ([`c6fd518`](https://github.com/Kitware/trame-server/commit/c6fd5189ada5edcdeaa99173badb72c7b7f3e8de))


## v2.9.0 (2023-02-08)

### Feature

* feat(client_type): Improve module handling to support vue2/3 ([`000899e`](https://github.com/Kitware/trame-server/commit/000899eac77d009281961ad68a98298e03752e42))


## v2.8.1 (2023-01-27)

### Fix

* fix(version): add trame_server.__version__

Partially addresses Kitware/trame#183

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`f6957f4`](https://github.com/Kitware/trame-server/commit/f6957f4dabee608c288ac841a38360fa286d1d67))

### Unknown

* Merge pull request #12 from Kitware/version

fix(version): add trame_server.__version__ ([`4c6c010`](https://github.com/Kitware/trame-server/commit/4c6c010b41ab4753631fe5bf07ff419e9285cb00))


## v2.8.0 (2023-01-21)

### Feature

* feat(on_server_start): Add new life cycle ([`0db1961`](https://github.com/Kitware/trame-server/commit/0db1961f36eee42dd1a16b0eb496104e8b2332b4))

### Fix

* fix(controller): Add @once helper ([`f25db26`](https://github.com/Kitware/trame-server/commit/f25db2636a6fbf7ddf5d0c3e9d8dbda97e471fa3))


## v2.7.2 (2023-01-20)

### Fix

* fix(dev): add hot reloading

This adds a `--hot-reload` option where, if set, controller/state callback functions will be
automatically reloaded for every function call. This excludes functions that are located in
site-packages directories (which are usually libraries that the user is not currently
developing).

There is also a `@hot_reload` decorator that may be added to functions as well, which will
cause the function to be reloaded every time.

This work is largely based off of https://github.com/julvo/reloading, with some major
modifications, including adding support for methods. His license is included within the
file.

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`5884ede`](https://github.com/Kitware/trame-server/commit/5884ede6a2662b830bba6d279d59abab0425e5e7))

### Unknown

* Merge pull request #9 from Kitware/hot-reload

fix(dev): add hot reloading ([`71be7d1`](https://github.com/Kitware/trame-server/commit/71be7d1f362e257be5921aa98b60d696e6767efe))


## v2.7.1 (2023-01-20)

### Fix

* fix: use host argument with wslink (#8)

Add environment variable fallback for host definition ([`8935e6a`](https://github.com/Kitware/trame-server/commit/8935e6a1c434f5054b1dda89482c34c4e1595276))


## v2.7.0 (2023-01-09)

### Feature

* feat(ready): Add ready future on server to await ([`6b72322`](https://github.com/Kitware/trame-server/commit/6b72322c06a5ade065355e2ffbd5d74206a89464))


## v2.6.1 (2022-12-10)

### Fix

* fix(corountine): Remove deprecated API for Py 3.11

Using inspect.isawaitable rather than asyncio.coroutine

fix #7 ([`82d945d`](https://github.com/Kitware/trame-server/commit/82d945d319c3f8c87c8797f4318e44b964e35e25))


## v2.6.0 (2022-12-06)

### Chore

* chore(security): Removed trailing whitespace ([`e242fed`](https://github.com/Kitware/trame-server/commit/e242fedaddc068372466e3e472523d45c3330c1d))

* chore(security): Fixed Formatting ([`005192d`](https://github.com/Kitware/trame-server/commit/005192d508d9abe1a3d8557637c3e7163d1048f1))

### Feature

* feat(security): Moved authKeyFile argument from wslink to trame-server ([`9c3b6fc`](https://github.com/Kitware/trame-server/commit/9c3b6fc5757fc6ca3ef1954f01216d64919d72e0))

* feat(security): Use authKeyFile argument if present ([`5c4fb3b`](https://github.com/Kitware/trame-server/commit/5c4fb3b227e8085073ce15dc3a9b5603db93b426))

### Unknown

* Merge pull request #6 from jwindgassen/authKeyFile

feat(security): Use authKeyFile argument if present ([`85b346c`](https://github.com/Kitware/trame-server/commit/85b346c132a9e6852689cd3c810984aed3dc5be4))


## v2.5.1 (2022-11-09)

### Fix

* fix(isascii): add python3.6 compatible isascii() method

If python &gt;= 3.7 is being used, just use the built-in `isascii()` method.
But if python &lt; 3.7, we have to use our own.

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`a957cdf`](https://github.com/Kitware/trame-server/commit/a957cdf9497aa72b3137cd9e390652311922b285))

### Unknown

* Merge pull request #5 from Kitware/isascii-python3.6

fix(isascii): add python3.6 compatible isascii() method ([`a7cb163`](https://github.com/Kitware/trame-server/commit/a7cb1633cc52fd5a2440237512449ff9e343172d))


## v2.5.0 (2022-10-27)

### Feature

* feat(state): report when state key is not serializable ([`fac8866`](https://github.com/Kitware/trame-server/commit/fac886650d53d052b79d70ac8b99a4847e98ca76))


## v2.4.1 (2022-10-26)

### Fix

* fix(file-upload): Properly filter fields for client sync

fix #3 ([`1656aab`](https://github.com/Kitware/trame-server/commit/1656aab27dddeea1a4128aef6f437a18dde395c6))


## v2.4.0 (2022-10-24)

### Feature

* feat(no-http): Add cmd option to disable HTTP serving ([`d34c471`](https://github.com/Kitware/trame-server/commit/d34c4719faf6ff1dc5d223ee3adbc42fb6d17d7c))


## v2.3.0 (2022-10-20)

### Feature

* feat(state): Allow state change to be async + add clean method ([`fa41cdd`](https://github.com/Kitware/trame-server/commit/fa41cdd8947319a0c685db9e5b835fca68175295))

### Fix

* fix(state): Better network handling for collaboration ([`b3b0e2f`](https://github.com/Kitware/trame-server/commit/b3b0e2fd3ef324f9512473993aff19f867c8cd61))


## v2.2.1 (2022-09-27)

### Fix

* fix(aiohttp.router): Simplify route management ([`245baaf`](https://github.com/Kitware/trame-server/commit/245baaf682ff27ed46df0ace473c6b8adcefe916))

* fix(controller): Add support for async tasks ([`45bf037`](https://github.com/Kitware/trame-server/commit/45bf037889e684044eb1431922b8f40f9621bd67))


## v2.2.0 (2022-09-22)

### Feature

* feat(wslink): Add lifecycle to allow web server routes to be added ([`9432cc8`](https://github.com/Kitware/trame-server/commit/9432cc855adc7430dc337c4efcd756c356304840))


## v2.1.6 (2022-08-12)

### Fix

* fix(wslink): Handle new --reverse-url cli arg

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`eb4eceb`](https://github.com/Kitware/trame-server/commit/eb4ecebab1c6e87fad501d74afad93a63852e005))

### Unknown

* Merge pull request #2 from Kitware/wslink-reverse-connection

fix(wslink): Handle new --reverse-url cli arg ([`6b4243f`](https://github.com/Kitware/trame-server/commit/6b4243f7a87fcc53888c6f645f6354e23950e8f5))


## v2.1.5 (2022-08-10)

### Chore

* chore(semantic-release): bump version to latest

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`efb63ce`](https://github.com/Kitware/trame-server/commit/efb63ce9c624e0a1a9d0f3d85ac0a05b17de90d8))

### Documentation

* docs(coverage): remove codecov PR comment

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`1ae8142`](https://github.com/Kitware/trame-server/commit/1ae81424e2af6fd7b5044da65d66777dddc07a42))

* docs(coverage): add setup.py to .coveragerc

This should not be included in the coverage since we will not run it with pytest.

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`ee4f01b`](https://github.com/Kitware/trame-server/commit/ee4f01b87e7e09c5641f0a0acf027d304b3cef8b))

### Fix

* fix(trigger): Allow triggers to return something ([`aebfb01`](https://github.com/Kitware/trame-server/commit/aebfb017889d7fc40690925cf457959896fa097a))

### Unknown

* doc(badge): add CI status badge

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`da28520`](https://github.com/Kitware/trame-server/commit/da28520f36723a476e4a46af44c6432da41b8476))

* doc(ci): turn off codecov statuses

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`ef21bc2`](https://github.com/Kitware/trame-server/commit/ef21bc297116e9d5847682e23cfea3e89390d95f))


## v2.1.4 (2022-06-14)

### Documentation

* docs(codecov): show coverage for all source files

This includes files that were not imported by the tests.

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`1c2b98e`](https://github.com/Kitware/trame-server/commit/1c2b98eae2a62860ed37adf3065fe42f5d48d218))

* docs(codecov): upload coverage to codecov

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`3a00af1`](https://github.com/Kitware/trame-server/commit/3a00af1cae74858d57e4bb5a7d961ab838ba5aba))

* docs(codecov): create and print coverage report

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`809a6de`](https://github.com/Kitware/trame-server/commit/809a6def95df2ead4d5172fa863b684851384898))

### Fix

* fix(desktop): add support for gui option ([`2d59706`](https://github.com/Kitware/trame-server/commit/2d59706b5bb209ccc181bffaf3c22065060a27fa))


## v2.1.3 (2022-06-10)

### Fix

* fix(state.update): Prevent equal value to trigger change ([`5d2d5e1`](https://github.com/Kitware/trame-server/commit/5d2d5e1563238d995a34b521f85a3fcba716e950))


## v2.1.2 (2022-06-10)

### Documentation

* docs(contributing): add CONTRIBUTING.rst

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`27212aa`](https://github.com/Kitware/trame-server/commit/27212aaea6a16843711a37337e4fdc439db5c4bb))

### Fix

* fix(state): Prevent equal value to trigger change ([`4c3165f`](https://github.com/Kitware/trame-server/commit/4c3165f9232d481f085845ed49c0b1c5109c1b81))


## v2.1.1 (2022-06-06)

### Fix

* fix(flush): Force flush for information print ([`fda6300`](https://github.com/Kitware/trame-server/commit/fda6300d42fa83d1350e8fb75412ec1314b03ba5))


## v2.1.0 (2022-06-04)

### Feature

* feat(ui): Introduce virtual node manager on server ([`f50551e`](https://github.com/Kitware/trame-server/commit/f50551ee1729204f208bc46f9200f4ad78d1197e))


## v2.0.2 (2022-05-30)

### Chore

* chore: downgrade python semantic release for fix

The newest version of semantic release has a bug that causes it to exit with errors. Downgrade to
the latest version without the bug.

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`fc07473`](https://github.com/Kitware/trame-server/commit/fc07473e85a56853faa5d55ab4d68b4b39917873))

* chore: rename publish =&gt; release in github action

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`d25c852`](https://github.com/Kitware/trame-server/commit/d25c8523c3810e8239f2883295f2236a4055c83a))

### Fix

* fix(state): No @state.change exec before server ready ([`50acbb5`](https://github.com/Kitware/trame-server/commit/50acbb5cdd867c981ea2b3d62948737c4ee4317c))


## v2.0.1 (2022-05-27)

### Chore

* chore(version): bump version to publish ([`eb07d9a`](https://github.com/Kitware/trame-server/commit/eb07d9ab5a5599053d0374ea7450459ce57a9daf))

### Documentation

* docs(api): Update controller api ([`b02b741`](https://github.com/Kitware/trame-server/commit/b02b741d5dd042a384124094625a5695ee0c3a42))

* docs(api): Add missing API docstring ([`00e8ad4`](https://github.com/Kitware/trame-server/commit/00e8ad41c1b2c003add6a3229cafbbc5ad2930dc))

### Fix

* fix: add github action for semantic release

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`661b74a`](https://github.com/Kitware/trame-server/commit/661b74a658dabf8ed1c837c6a5e4ab53f368210a))

* fix(vue_use): Fix typo in &#39;reduce_vue_use&#39;

Could not pass options before like this: vue_use = [(&#39;trame_component&#39;, {...})] ([`37823d4`](https://github.com/Kitware/trame-server/commit/37823d4a361f01ca286a5090dbde984a5481c842))

* fix(controller): Add decorator for &#39;set&#39; and &#39;add&#39; ([`28894d3`](https://github.com/Kitware/trame-server/commit/28894d3a6a52e85b63d744181d19d66ab8020819))

* fix(kwarg): improve **kwarg handling in server.start ([`218400d`](https://github.com/Kitware/trame-server/commit/218400d8737e8d92cd601ec07ca3a9d14b451702))

* fix(async): Fix method call ([`ddf6938`](https://github.com/Kitware/trame-server/commit/ddf693883f986ae52b57ef0351479df99f2ed4a2))

* fix(async): export task decorator ([`0fb23e9`](https://github.com/Kitware/trame-server/commit/0fb23e990985ccaa2761b5b8f4342ea44a476e26))

* fix(vue_use): Reduce duplicate and merge options ([`a8ce28b`](https://github.com/Kitware/trame-server/commit/a8ce28b56090f00c5eddd4c9f8390b63dff6f09a))

### Unknown

* Merge pull request #1 from DavidBerger98/fix-vue_use

fix(vue_use): Fix typo in &#39;reduce_vue_use&#39; ([`76a0469`](https://github.com/Kitware/trame-server/commit/76a0469c6615317deed755bc10057fcf57b7db7e))

* Add &#34;Pytest&#34; to test names

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`7ad092d`](https://github.com/Kitware/trame-server/commit/7ad092ddb2a242f72c1ada857c4ccfb194ba5272))

* Bump rc version to test pypi upload

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`37131ce`](https://github.com/Kitware/trame-server/commit/37131ce4ecdca42f4c8eabed4f0968b209fd1baf))

* Combine workflows and add publishing

The workflows are combined because publishing depends on testing and
pre-committing.

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`e90f03a`](https://github.com/Kitware/trame-server/commit/e90f03a3e5b2a0d024c0579bf151c151bcb77e6b))

* Add link to trame in docs

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`c81ece3`](https://github.com/Kitware/trame-server/commit/c81ece345caa1d5ace5d918e4800f0e2d2d4a178))

* Add first pass at .readthedocs.yaml

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`56380cd`](https://github.com/Kitware/trame-server/commit/56380cdd3cae6d72986c57021f0982dbf3cdf086))

* Add first pass at API docs

Signed-off-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`074ab09`](https://github.com/Kitware/trame-server/commit/074ab0979a7078bab470c9be15c45983e544cd88))

* Trame v2 - server implementation

This initial commit gather the first stage of what the server side of trame 2.0.0 aims to be.

Co-authored-by: Patrick Avery &lt;patrick.avery@kitware.com&gt; ([`464af41`](https://github.com/Kitware/trame-server/commit/464af41ce291274dfb9024efd1fac5cf2bda1220))

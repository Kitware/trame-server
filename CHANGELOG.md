# Changelog

<!--next-version-placeholder-->

## v2.10.0 (2023-03-27)
### Feature
* **args:** Allow trame args to be specified separately ([`d2600c3`](https://github.com/Kitware/trame-server/commit/d2600c32a2acb18c7f700239e37581df85c9f57d))
* **ArgumentParser:** Subclass and allow parsing disable ([`22746dd`](https://github.com/Kitware/trame-server/commit/22746dd171f2aca4ea2c6675eefd6ffc242c5f95))

## v2.9.1 (2023-02-15)
### Fix
* **on_server_exited:** Run exit tasks till completion for exec_mode=main ([`876d536`](https://github.com/Kitware/trame-server/commit/876d536e9f830feea96c4f60a18710fa5c8839a0))
* **task_funcs:** Allow controller with only task_funcs ([`c6fd518`](https://github.com/Kitware/trame-server/commit/c6fd5189ada5edcdeaa99173badb72c7b7f3e8de))

## v2.9.0 (2023-02-08)
### Feature
* **client_type:** Improve module handling to support vue2/3 ([`000899e`](https://github.com/Kitware/trame-server/commit/000899eac77d009281961ad68a98298e03752e42))

## v2.8.1 (2023-01-27)
### Fix
* **version:** Add trame_server.__version__ ([`f6957f4`](https://github.com/Kitware/trame-server/commit/f6957f4dabee608c288ac841a38360fa286d1d67))

## v2.8.0 (2023-01-21)
### Feature
* **on_server_start:** Add new life cycle ([`0db1961`](https://github.com/Kitware/trame-server/commit/0db1961f36eee42dd1a16b0eb496104e8b2332b4))

### Fix
* **controller:** Add @once helper ([`f25db26`](https://github.com/Kitware/trame-server/commit/f25db2636a6fbf7ddf5d0c3e9d8dbda97e471fa3))

## v2.7.2 (2023-01-20)
### Fix
* **dev:** Add hot reloading ([`5884ede`](https://github.com/Kitware/trame-server/commit/5884ede6a2662b830bba6d279d59abab0425e5e7))

## v2.7.1 (2023-01-20)
### Fix
* Use host argument with wslink ([#8](https://github.com/Kitware/trame-server/issues/8)) ([`8935e6a`](https://github.com/Kitware/trame-server/commit/8935e6a1c434f5054b1dda89482c34c4e1595276))

## v2.7.0 (2023-01-09)
### Feature
* **ready:** Add ready future on server to await ([`6b72322`](https://github.com/Kitware/trame-server/commit/6b72322c06a5ade065355e2ffbd5d74206a89464))

## v2.6.1 (2022-12-10)
### Fix
* **corountine:** Remove deprecated API for Py 3.11 ([`82d945d`](https://github.com/Kitware/trame-server/commit/82d945d319c3f8c87c8797f4318e44b964e35e25))

## v2.6.0 (2022-12-06)
### Feature
* **security:** Moved authKeyFile argument from wslink to trame-server ([`9c3b6fc`](https://github.com/Kitware/trame-server/commit/9c3b6fc5757fc6ca3ef1954f01216d64919d72e0))
* **security:** Use authKeyFile argument if present ([`5c4fb3b`](https://github.com/Kitware/trame-server/commit/5c4fb3b227e8085073ce15dc3a9b5603db93b426))

## v2.5.1 (2022-11-09)
### Fix
* **isascii:** Add python3.6 compatible isascii() method ([`a957cdf`](https://github.com/Kitware/trame-server/commit/a957cdf9497aa72b3137cd9e390652311922b285))

## v2.5.0 (2022-10-27)
### Feature
* **state:** Report when state key is not serializable ([`fac8866`](https://github.com/Kitware/trame-server/commit/fac886650d53d052b79d70ac8b99a4847e98ca76))

## v2.4.1 (2022-10-26)
### Fix
* **file-upload:** Properly filter fields for client sync ([`1656aab`](https://github.com/Kitware/trame-server/commit/1656aab27dddeea1a4128aef6f437a18dde395c6))

## v2.4.0 (2022-10-24)
### Feature
* **no-http:** Add cmd option to disable HTTP serving ([`d34c471`](https://github.com/Kitware/trame-server/commit/d34c4719faf6ff1dc5d223ee3adbc42fb6d17d7c))

## v2.3.0 (2022-10-20)
### Feature
* **state:** Allow state change to be async + add clean method ([`fa41cdd`](https://github.com/Kitware/trame-server/commit/fa41cdd8947319a0c685db9e5b835fca68175295))

### Fix
* **state:** Better network handling for collaboration ([`b3b0e2f`](https://github.com/Kitware/trame-server/commit/b3b0e2fd3ef324f9512473993aff19f867c8cd61))

## v2.2.1 (2022-09-27)
### Fix
* **aiohttp.router:** Simplify route management ([`245baaf`](https://github.com/Kitware/trame-server/commit/245baaf682ff27ed46df0ace473c6b8adcefe916))
* **controller:** Add support for async tasks ([`45bf037`](https://github.com/Kitware/trame-server/commit/45bf037889e684044eb1431922b8f40f9621bd67))

## v2.2.0 (2022-09-22)
### Feature
* **wslink:** Add lifecycle to allow web server routes to be added ([`9432cc8`](https://github.com/Kitware/trame-server/commit/9432cc855adc7430dc337c4efcd756c356304840))

## v2.1.6 (2022-08-12)
### Fix
* **wslink:** Handle new --reverse-url cli arg ([`eb4eceb`](https://github.com/Kitware/trame-server/commit/eb4ecebab1c6e87fad501d74afad93a63852e005))

## v2.1.5 (2022-08-10)
### Fix
* **trigger:** Allow triggers to return something ([`aebfb01`](https://github.com/Kitware/trame-server/commit/aebfb017889d7fc40690925cf457959896fa097a))

### Documentation
* **coverage:** Remove codecov PR comment ([`1ae8142`](https://github.com/Kitware/trame-server/commit/1ae81424e2af6fd7b5044da65d66777dddc07a42))
* **coverage:** Add setup.py to .coveragerc ([`ee4f01b`](https://github.com/Kitware/trame-server/commit/ee4f01b87e7e09c5641f0a0acf027d304b3cef8b))

## v2.1.4 (2022-06-14)
### Fix
* **desktop:** Add support for gui option ([`2d59706`](https://github.com/Kitware/trame-server/commit/2d59706b5bb209ccc181bffaf3c22065060a27fa))

### Documentation
* **codecov:** Show coverage for all source files ([`1c2b98e`](https://github.com/Kitware/trame-server/commit/1c2b98eae2a62860ed37adf3065fe42f5d48d218))
* **codecov:** Upload coverage to codecov ([`3a00af1`](https://github.com/Kitware/trame-server/commit/3a00af1cae74858d57e4bb5a7d961ab838ba5aba))
* **codecov:** Create and print coverage report ([`809a6de`](https://github.com/Kitware/trame-server/commit/809a6def95df2ead4d5172fa863b684851384898))

## v2.1.3 (2022-06-10)
### Fix
* **state.update:** Prevent equal value to trigger change ([`5d2d5e1`](https://github.com/Kitware/trame-server/commit/5d2d5e1563238d995a34b521f85a3fcba716e950))

## v2.1.2 (2022-06-10)
### Fix
* **state:** Prevent equal value to trigger change ([`4c3165f`](https://github.com/Kitware/trame-server/commit/4c3165f9232d481f085845ed49c0b1c5109c1b81))

### Documentation
* **contributing:** Add CONTRIBUTING.rst ([`27212aa`](https://github.com/Kitware/trame-server/commit/27212aaea6a16843711a37337e4fdc439db5c4bb))

## v2.1.1 (2022-06-06)
### Fix
* **flush:** Force flush for information print ([`fda6300`](https://github.com/Kitware/trame-server/commit/fda6300d42fa83d1350e8fb75412ec1314b03ba5))

## v2.1.0 (2022-06-04)
### Feature
* **ui:** Introduce virtual node manager on server ([`f50551e`](https://github.com/Kitware/trame-server/commit/f50551ee1729204f208bc46f9200f4ad78d1197e))

## v2.0.2 (2022-05-30)
### Fix
* **state:** No @state.change exec before server ready ([`50acbb5`](https://github.com/Kitware/trame-server/commit/50acbb5cdd867c981ea2b3d62948737c4ee4317c))

## v2.0.1 (2022-05-27)
### Fix
* Add github action for semantic release ([`661b74a`](https://github.com/Kitware/trame-server/commit/661b74a658dabf8ed1c837c6a5e4ab53f368210a))
* **vue_use:** Fix typo in 'reduce_vue_use' ([`37823d4`](https://github.com/Kitware/trame-server/commit/37823d4a361f01ca286a5090dbde984a5481c842))
* **controller:** Add decorator for 'set' and 'add' ([`28894d3`](https://github.com/Kitware/trame-server/commit/28894d3a6a52e85b63d744181d19d66ab8020819))
* **kwarg:** Improve **kwarg handling in server.start ([`218400d`](https://github.com/Kitware/trame-server/commit/218400d8737e8d92cd601ec07ca3a9d14b451702))
* **async:** Fix method call ([`ddf6938`](https://github.com/Kitware/trame-server/commit/ddf693883f986ae52b57ef0351479df99f2ed4a2))
* **async:** Export task decorator ([`0fb23e9`](https://github.com/Kitware/trame-server/commit/0fb23e990985ccaa2761b5b8f4342ea44a476e26))
* **vue_use:** Reduce duplicate and merge options ([`a8ce28b`](https://github.com/Kitware/trame-server/commit/a8ce28b56090f00c5eddd4c9f8390b63dff6f09a))

### Documentation
* **api:** Update controller api ([`b02b741`](https://github.com/Kitware/trame-server/commit/b02b741d5dd042a384124094625a5695ee0c3a42))
* **api:** Add missing API docstring ([`00e8ad4`](https://github.com/Kitware/trame-server/commit/00e8ad41c1b2c003add6a3229cafbbc5ad2930dc))

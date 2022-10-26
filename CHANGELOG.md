# Changelog

<!--next-version-placeholder-->

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

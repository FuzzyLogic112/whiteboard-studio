"""测试期的全局准备。

必须在任何 app 模块被导入之前设好 WBS_WORKSPACE：`app.config.settings` 是
导入时构造的单例，晚了就来不及了，测试会往仓库里的 .workspace 写东西。
conftest 由 pytest 最先加载，正好是这个时机。
"""

import os
import tempfile

os.environ.setdefault("WBS_WORKSPACE", tempfile.mkdtemp(prefix="wbs-tests-"))

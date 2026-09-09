1、网络搜索PaddleOCR的使用方法
2、http://192.168.0.70:5564 --model_name PaddleOCR-VL-1.5-0.9B --port 5564，
研究PaddleOCR-VL模型调用方式最大并发数，了解它支持的所有转换格式
3、https://aistudio.baidu.com/paddleocr 是他的一个orc网站,
4、可以看看/opt/webapp/mineru_html/的转化流程控制，要能服务器后台执行，并可关闭浏览器
5、可能用到的/skill frontend-design web-artifacts-builder webapp-testing
6、编制一个python程序，考虑多人并发客户端，异步队列 + 流式进度，适合多人同时上传大文件
7、有github连接可点击前往
8、了解/opt/yz/yz-login/ integration-guide.md的登录方式，不要修改/opt/yz/yz-login/，并实现登录
9、普通用户管理自己的上传、ocr，删除、下载、队列。管理员管理各种参数全部权限暂管理、暂停/清空/删除
10、WebSocket 实时进度

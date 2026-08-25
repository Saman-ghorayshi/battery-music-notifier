import faulthandler, sys, time
faulthandler.dump_traceback_later(8, exit=True)
t0 = time.time()
from battery_notifier.config import Config
cfg = Config(); cfg.music_files = []; cfg.socket_secret = ""
print("config ok", round(time.time() - t0, 2), flush=True)
from battery_notifier.remote import NotificationServer
print("remote imported", round(time.time() - t0, 2), flush=True)
srv = NotificationServer(cfg, "0.0.0.0", 8803, conn_mode="local")
print("constructed", round(time.time() - t0, 2), flush=True)

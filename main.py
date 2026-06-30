from battery_notifier.battery import Battery
from battery_notifier.player import Player
from battery_notifier.notifier import Notifier

if __name__ == "__main__":
    b = Battery()
    info = b.read()
    print(f"Battery: {info.percentage}% Charging: {info.charging}")

    p = Player(["./test.wav"], volume=0.5)
    p.play()

    n = Notifier()
    n.send("Test", "It works!")

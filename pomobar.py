#!/usr/bin/env python

import argparse
import datetime
import dbus
import pathlib
import shelve
import sys
import yaml

from enum import Enum


DEFAULT_NUM_SETS = 4
DEFAULT_WORK_LENGTH = 25 * 60
DEFAULT_SHORT_BREAK_LENGTH = 5 * 60
DEFAULT_LONG_BREAK_LENGTH = 20 * 60
DEFAULT_AUTOSTART_WORK = False
DEFAULT_AUTOSTART_BREAK = True


class Mode(Enum):
    RUNNING = 1
    STOPPED = 2


class Phase(Enum):
    WORK = 1
    SHORT_BREAK = 2
    LONG_BREAK = 3


class Urgency(Enum):
    LOW = 0
    NORMAL = 1
    CRITICAL = 2

class Pomodoro():
    def __init__(self, state_file, config):
        self.state_file = state_file
        self.config = config
        self.current_mode = Mode.STOPPED
        self.timer = self.config['WORK_LENGTH']
        self.phase = Phase.WORK
        self.set = 0
        self.last_updated = datetime.datetime.now()

    def __str__(self):
        state_str = f"Pomodoro: "
        state_str += f"state_file: {self.state_file}, "
        state_str += f"current_mode: {self.current_mode}, "
        state_str += f"timer: {self.timer}, "
        state_str += f"phase: {self.phase}, "
        state_str += f"set: {self.set + 1}, "
        return state_str

    def update(self, config):
        self.update_config(config)
        self.update_time()

        self._write_state()

    def update_config(self, config):
        self.config = config

    def update_time(self):
        if self.current_mode == Mode.RUNNING:
            dt = datetime.datetime.now() - self.last_updated
            if self.timer > 0:
                self.timer -= dt.total_seconds()
                if self.timer <= 0:
                    self.increment_phase()
                    alert()

    def increment_phase(self, autostart_override=None):
        self.current_mode = Mode.STOPPED
        if self.phase == Phase.WORK:
            if (self.set+1) % self.config['NUM_SETS'] == 0:
                self.phase = Phase.LONG_BREAK
                self.timer = self.config['LONG_BREAK_LENGTH']
            else:
                self.phase = Phase.SHORT_BREAK
                self.timer = self.config['SHORT_BREAK_LENGTH']
            if self.config['AUTOSTART_BREAK'] and autostart_override is None:
                self.current_mode = Mode.RUNNING
            elif autostart_override is not None and autostart_override == True:
                self.current_mode = Mode.RUNNING
        else:
            self.phase = Phase.WORK
            self.timer = self.config['WORK_LENGTH']
            self.set += 1
            if self.config['AUTOSTART_WORK'] and autostart_override is None:
                self.current_mode = Mode.RUNNING
            elif autostart_override is not None and autostart_override == True:
                self.current_mode = Mode.RUNNING


    def debug(self):
        pomo = self._retrieve_state()
        print(f"D: {pomo}")

    def report(self):
        pomo = self._retrieve_state()

        hours = int(pomo.timer / 3600)
        remainder = ((pomo.timer / 3600) - hours) * 3600
        minutes = int(remainder / 60)
        seconds = pomo.timer % 60

        set = pomo.set + 1

        line = f"{hours:02d}:{minutes:02d}:{int(seconds):02d} #{set}"

        line_formatted = ""
        match pomo.current_mode:
            case Mode.RUNNING:
                line_formatted = line
            case Mode.STOPPED:
                line_formatted = "%{F#CB4B16}" + line + "%{F#839496}"

        phase_icon = ""
        match pomo.phase:
            case Phase.WORK:
                phase_icon = "󱌣"
            case Phase.SHORT_BREAK:
                phase_icon = "󰒲"
            case Phase.LONG_BREAK:
                phase_icon = ""
        phase_icon_formatted = "%{F#859900}%{T2}" + phase_icon + "%{T-}%{F#839496}"

        line = phase_icon + " " + line
        line_formatted = phase_icon_formatted + " " + line_formatted

        print(line_formatted)

    def start(self):
        self.current_mode = Mode.RUNNING
        self._write_state()

    def stop(self):
        self.current_mode = Mode.STOPPED
        self._write_state()

    def skip(self):
        self.increment_phase(False)
        self._write_state()

    def reset(self):
        self.current_mode = Mode.STOPPED
        self.timer = self.config['WORK_LENGTH']
        self.phase = Phase.WORK
        self.set = 0
        self._write_state()

    def _retrieve_state(self):
        pomo = None
        with shelve.open(self.state_file) as db:
            pomo = db['state']
        return pomo

    def _write_state(self):
        self.last_updated = datetime.datetime.now()
        with shelve.open(self.state_file) as db:
            db['state'] = self


def tick(state, config):
    pomo = None
    if state.exists():
        with shelve.open(state) as db:
            pomo = db['state']
        pomo.update(config)
    else:
        pomo = Pomodoro(state, config)
        with shelve.open(state) as db:
            db['state'] = pomo
    return pomo


def alert():
    _send_notification("Timer expired!", "Time to start/stop", Urgency.NORMAL)

def _send_notification(summary, body, urgency=Urgency.NORMAL, timeout=5000):

    bus = dbus.SessionBus()
    notif = bus.get_object('org.freedesktop.Notifications', 
                           '/org/freedesktop/Notifications')
    interface = dbus.Interface(notif, 'org.freedesktop.Notifications')
 
    # Notify arguments:
    # app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout
    interface.Notify("Pomobar",
                     0,
                     "",
                     summary,
                     body,
                     [],
                     {"urgency": urgency.value},
                     timeout)

def load_config(config_file):
    try:
        with open(config_file, 'r') as stream:
            try:
                config_data = yaml.safe_load(stream)
                return config_data
            except yaml.YAMLError as e:
                # debug logging
                print("Failed to parse config file")
                return None
    except Exception as e:
        # debug logging
        print("Failed to open config file")
        return None


def default_config():
    return {
            'NUM_SETS': DEFAULT_NUM_SETS,
            'WORK_LENGTH': DEFAULT_WORK_LENGTH,
            'SHORT_BREAK_LENGTH': DEFAULT_SHORT_BREAK_LENGTH,
            'LONG_BREAK_LENGTH': DEFAULT_LONG_BREAK_LENGTH,
            'AUTOSTART_WORK': DEFAULT_AUTOSTART_WORK,
            'AUTOSTART_BREAK': DEFAULT_AUTOSTART_BREAK
           }

def main(argv=None):
    if argv is None:
        argv = sys.argv
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file",
                        default="./.pomobar.state",
                        help="Path to pomobar state file")
    parser.add_argument("--config-file",
                        default="./config.yaml",
                        help="Path to configuration file")
    parser.add_argument("mode",
                        choices=["report", "start", "stop", "skip", "reset"],
                        default="report",
                        help="Operation mode")

    # Add optional --lockin arg to start and stop
    # Allows for stopwatch to just keep working instead of forcing breaks

    args = parser.parse_args()
    state_file = pathlib.Path(args.state_file)

    config = load_config(args.config_file)
    if config is None:
        config = default_config()
 
    pomo = tick(state_file, config)

    match args.mode:
        case "report":
            pomo.report()
        case "start":
            if pomo.current_mode == Mode.STOPPED:
                pomo.start()
            else:
                pomo.stop()
        case "stop":
            pomo.stop()
        case "skip":
            pomo.skip()
        case "reset":
            pomo.reset()


if __name__ == "__main__":
    main()

import logging
import datetime

class PrettyFormatter(logging.Formatter):
    def __init__(self, fmt = None, datefmt = None, style = "%", validate = True, *, defaults = None):
        super().__init__(fmt, datefmt, style, validate, defaults=defaults)

    def format(self, record):
        # log time
        f_time = datetime.datetime.fromtimestamp(record.created)
        if self.datefmt:
            f_time = f_time.strftime(self.datefmt)
        f_time = '{:^22s}'.format(f_time)
        
        # log level name
        f_level_name = record.levelname
        f_level_name = '{:^8s}'.format(f_level_name)
        
        # log source
        f_source = f"{record.filename}:{record.lineno}"
        f_source = '{:^16s}'.format(f_source)

        # log content
        f_message = record.msg

        return f"[{f_time}] [{f_level_name}] [{f_source}]: {f_message}"
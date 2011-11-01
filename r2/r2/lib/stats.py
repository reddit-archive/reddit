class Stats:
    def __init__(self, addr, sample_rate):
        if addr:
            import statsd
            self.statsd = statsd
            self.host, port = addr.split(':')
            self.port = int(port)
            self.sample_rate = sample_rate
            self.connection = self.statsd.connection.Connection(
                self.host, self.port, self.sample_rate)
        else:
            self.host = None
            self.port = None
            self.sample_rate = None
            self.connection = None

    def get_timer(self, name):
        if self.connection:
            return self.statsd.timer.Timer(name, self.connection)
        else:
            return None

    def transact(self, action, service_time_sec):
        timer = self.get_timer('service_time')
        if timer:
            timer.send(action, service_time_sec)

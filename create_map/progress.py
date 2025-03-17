class ProgressTracker:
    def __init__(self, min_value, max_value, on_progress):
        assert min_value < max_value
        self.min_value = min_value
        self.max_value = max_value
        self.range = max_value - min_value
        self.on_progress = on_progress
        self._last_value = None

    def step(self, value):
        """
        Update progress by a fraction of the total range
        """
        assert 0 <= value <= 1
        if value != self._last_value:
            self.on_progress(value * self.range + self.min_value)
            self._last_value = value

    def sub(self, min_value, max_value):
        """
        Create a sub-progress tracker
        """
        def on_progress(value):
            self.step(value * (max_value - min_value) + min_value)
        return ProgressTracker(0, 1, on_progress)
    
    def over_range(self, min_value, max_value, iterable):
        """
        Create a sub-progress tracker that goes over the range
        """
        sub = self.sub(min_value, max_value)
        # If iterable does not have a length, convert it to a list to get the count
        if not hasattr(iterable, '__len__'):
            iterable = list(iterable)
        count = len(iterable)
        for i, x in enumerate(iterable):
            sub.step(i / count)
            yield x
        sub.step(1)
        
NoProgress = ProgressTracker(0, 1, lambda x: None)
#!/usr/bin/env python

def get_time(e, prop):
    times = e._element.find('Times')
    if times is not None:
        prop = times.find(prop)
        if prop is not None:
            return decode_time(prop.text)

def set_time(e, prop, value):
    times = e._element.find('Times')
    if times is not None:
        prop = times.find(prop)
        if prop is not None:
            prop.text = encode_time(value)

def get_text(self, tag):
    v = self._element.find(tag)
    if v is not None:
        return v.text

def set_text(self, tag, value):
    v = self._element.find(tag)
    if v is not None:
        self._element.remove(v)
    self._element.append(getattr(E, tag)(value))

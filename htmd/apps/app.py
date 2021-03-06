# (c) 2015-2016 Acellera Ltd http://www.acellera.com
# All Rights Reserved
# Distributed under HTMD Software License Agreement
# No redistribution in whole or part
#
import abc
from abc import ABCMeta


class RetrieveError(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class SubmitError(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class InProgressError(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class ProjectNotExistError(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class App(metaclass=ABCMeta):

    @abc.abstractmethod
    def retrieve(self):
        """ Subclasses need to implement this method """
        pass

    @abc.abstractmethod
    def submit(self, dirs):
        """ Subclasses need to implement this method """
        pass

    @abc.abstractmethod
    def inprogress(self):
        """ Subclasses need to implement this method """
        pass

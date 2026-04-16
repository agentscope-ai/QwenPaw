# -*- coding: utf-8 -*-
"""
Contract Test Framework

Provides abstract contract tests that enforce all subclasses follow
the same interface contract. When a base class changes, all subclass
tests automatically validate they still satisfy the contract.

Example:
    class MyBaseContract(BaseContractTest):
        @abstractmethod
        def create_instance(self):
            pass

        def test_contract(self, instance):
            # Runs for ALL subclasses
            assert hasattr(instance, 'required_method')

    class TestMyImpl(MyBaseContract):
        def create_instance(self):
            return MyImpl()
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import Any

import pytest


class BaseContractTest(ABC):
    """
    Base class for contract tests.

    Subclasses must implement `create_instance()` to provide an instance
    of the class being tested. All test methods defined here automatically
    run for each subclass.

    Example:
        class MyBaseContract(BaseContractTest):
            @abstractmethod
            def create_instance(self) -> MyBase:
                pass

            def test_has_required_method(self, instance):
                assert hasattr(instance, 'required_method')

        class TestMyImpl(MyBaseContract):
            def create_instance(self):
                return MyImpl()
    """

    @abstractmethod
    def create_instance(self) -> Any:
        """
        Create and return an instance of the class under test.

        Must be implemented by each concrete test subclass.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement create_instance()",
        )

    @pytest.fixture
    def instance(self) -> Any:
        """Fixture that provides the instance from create_instance()."""
        return self.create_instance()

    @classmethod
    def get_concrete_tests(cls) -> list[type]:
        """
        Get all concrete (non-abstract) test subclasses.

        Returns:
            List of test classes that inherit from this contract.
        """
        subclasses = []
        for subclass in cls.__subclasses__():
            # Check if it's a concrete implementation (not abstract)
            if not inspect.isabstract(subclass):
                subclasses.append(subclass)
            # Recursively get subclasses
            subclasses.extend(subclass.get_concrete_tests())
        return subclasses


__all__ = [
    "BaseContractTest",
]

from __future__ import annotations

import abc
import dataclasses
import re
from typing import Any, Callable, Literal, TypeVar

T = TypeVar("T")
FilterOperatorType = Literal["eq", "ne", "includes", "excludes"]


@dataclasses.dataclass
class FilterableAttribute:
    name: str
    annotation: str

    @property
    def operators(self) -> frozenset[FilterOperatorType]:
        annotation = self.annotation
        ops = set()

        if match := re.match(r"^ClassVar\[(.*)\]$", self.annotation):
            annotation = match.group(1).strip()

        if match := re.match(r"^Optional\[(.*)\]$", annotation):
            annotation = match.group(1).strip()
        elif match := re.match(r"^(.*) \| None$", annotation):
            annotation = match.group(1).strip()

        if annotation in ("str",):
            ops |= {"eq", "ne"}
        elif annotation in ("list[str]", "set[str]", "frozenset[str]"):
            ops |= {"includes", "excludes"}

        return frozenset(ops)

    def build_filter(self, operator: FilterOperatorType, value: Any) -> Callable[[Any], bool]:
        if operator not in self.operators:
            raise ValueError("Operator is not supported for this attribute", self, operator, value)

        match operator:
            case "eq":
                return lambda x: value == getattr(x, self.name)
            case "ne":
                return lambda x: value != getattr(x, self.name)
            case "includes":
                return lambda x: value in (getattr(x, self.name) or [])
            case "excludes":
                return lambda x: value not in (getattr(x, self.name) or [])

        raise ValueError("Unexpected operator", self, operator, value)


@dataclasses.dataclass
class FilterPart:
    name: str
    operator: FilterOperatorType
    value: str


class FilterableMixin(abc.ABC):
    """
    Adds support for filtering by instance attributes.
    - Only string attributes (or collections of strings) are supported
    - Attributes must be annotated on class, or defined with annotated @property decorator
    """

    @classmethod
    def _get_filterable_attributes(cls) -> dict[str, FilterableAttribute]:
        attrs = {}

        # get attributes form base classes

        for base in cls.__bases__:
            if issubclass(base, FilterableMixin):
                attrs |= base._get_filterable_attributes()

        # annotated class/instance variables

        for name, type_ in cls.__dict__.get("__annotations__", {}).items():
            if not name.startswith("_"):
                attrs[name] = FilterableAttribute(name=name, annotation=type_)

        # @property values

        for name, value in cls.__dict__.items():
            # noinspection PyUnresolvedReferences
            if (
                not name.startswith("_")
                and isinstance(value, property)
                and hasattr(value.fget, "__annotations__")
                and "return" in value.fget.__annotations__
            ):
                attrs[name] = FilterableAttribute(name=name, annotation=value.fget.__annotations__["return"])

        # return only filterable types (only str types are supported)

        return {attr.name: attr for attr in attrs.values() if attr.operators}

    @classmethod
    def build_str_filter(cls: type[T], *str_parts: str) -> Callable[[T], bool]:
        """
        `['id:eq:foo'] -> `lambda x: x.id == "foo"``
        """
        filter_parts = []
        for str_part in str_parts:
            name, operator, value = str_part.split(":", maxsplit=2)
            filter_parts.append(FilterPart(name=name, operator=operator, value=value))

        return cls.build_filter(*filter_parts)

    @classmethod
    def build_filter(cls: type[T], *parts: FilterPart) -> Callable[[T], bool]:
        attrs = cls._get_filterable_attributes()
        part_filters = []

        for part in parts:
            if part.name not in attrs:
                raise ValueError("Not filterable attribute", part, cls.__name__, attrs)
            part_filters.append(attrs[part.name].build_filter(part.operator, part.value))

        return lambda x: all(part_filter(x) for part_filter in part_filters)

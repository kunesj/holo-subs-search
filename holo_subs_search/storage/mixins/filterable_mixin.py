from __future__ import annotations

import abc
import datetime
import functools
import inspect
from typing import Any, Callable, Literal, TypeVar, Union, get_type_hints

import pydantic

from ...utils import NoneType, iter_typing_types

T = TypeVar("T")
FilterOperatorType = Literal["eq", "ne", "lt", "le", "gt", "ge", "includes", "excludes"]

EQ_TYPES = [(x,) for x in (str, int, float, bool, NoneType, datetime.datetime, datetime.date, datetime.timedelta)]
CMP_TYPES = [(x,) for x in (int, float, datetime.datetime, datetime.date, datetime.timedelta)]
IN_TYPES = [(iter_type, item_type) for iter_type in (list, tuple, set, frozenset) for (item_type,) in EQ_TYPES]


class FilterableAttribute(pydantic.BaseModel):
    name: str
    typing: Any

    @functools.cached_property
    def root_adapter(self) -> pydantic.TypeAdapter:
        root_types = {types_[0] for types_ in iter_typing_types(self.typing)}
        return pydantic.TypeAdapter(Union[*root_types])

    @functools.cached_property
    def item_adapter(self) -> pydantic.TypeAdapter:
        item_types = {types_[1] for types_ in iter_typing_types(self.typing) if types_ in IN_TYPES}
        return pydantic.TypeAdapter(Union[*item_types])

    @property
    def operators(self) -> frozenset[FilterOperatorType]:
        ops = set()

        for types_ in iter_typing_types(self.typing):
            if types_ in EQ_TYPES:
                ops |= {"eq", "ne"}

            if types_ in CMP_TYPES:
                ops |= {"lt", "le", "gt", "ge"}

            if types_ in IN_TYPES:
                ops |= {"includes", "excludes"}

        return frozenset(ops)

    def build_filter(self, operator: FilterOperatorType, value: str) -> Callable[[Any], bool]:
        if operator not in self.operators:
            raise ValueError("Operator is not supported for this attribute", self, operator, value)

        match operator:
            case "eq":
                value = self.root_adapter.validate_python(value)
                return lambda x: getattr(x, self.name) == value
            case "ne":
                value = self.root_adapter.validate_python(value)
                return lambda x: getattr(x, self.name) != value
            case "lt":
                value = self.root_adapter.validate_python(value)
                return lambda x: getattr(x, self.name) < value
            case "le":
                value = self.root_adapter.validate_python(value)
                return lambda x: getattr(x, self.name) <= value
            case "gt":
                value = self.root_adapter.validate_python(value)
                return lambda x: getattr(x, self.name) > value
            case "ge":
                value = self.root_adapter.validate_python(value)
                return lambda x: getattr(x, self.name) >= value
            case "includes":
                value = self.item_adapter.validate_python(value)
                return lambda x: value in (getattr(x, self.name) or [])
            case "excludes":
                value = self.item_adapter.validate_python(value)
                return lambda x: value not in (getattr(x, self.name) or [])

        raise ValueError("Unexpected operator", self, operator, value)


class FilterPart(pydantic.BaseModel):
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

        for klass in reversed(inspect.getmro(cls)):
            # annotated class/instance variables
            # - include_extras=True is required to keep Annotated data

            for name, typing_ in get_type_hints(klass, include_extras=True).items():
                attrs[name] = FilterableAttribute(name=name, typing=typing_)

            # @property values

            for name, value in klass.__dict__.items():
                if not name.startswith("_") and isinstance(value, property):
                    type_hints = get_type_hints(value.fget, include_extras=True)
                    if "return" in type_hints:
                        attrs[name] = FilterableAttribute(name=name, typing=type_hints["return"])

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
                raise ValueError("Not filterable attribute", part, cls.__name__, [*attrs.values()])
            part_filters.append(attrs[part.name].build_filter(part.operator, part.value))

        return lambda x: all(part_filter(x) for part_filter in part_filters)

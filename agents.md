# Python Best Practices

This repository is a Home Assistant custom integration.

* Prefer Home Assistant conventions and the existing repo structure over generic Python package guidance
* Keep code in the integration-style layout used by this repo and do not introduce a `src/` layout
* Use Home Assistant config entries, options flows, and integration storage patterns for configuration
* Apply only the guidance in this file that is relevant to the task at hand
* Always update the manifest version when making a set of changes.

## Folder Structure

```text
root
├─ custom_components/
│   └─ mesh_solar/
│       ├─ local_docs           # integration documentation
│       ├─ sensors              # sensors
│       ├─ translations         # languages
│       ├─ __init__.py
│       ├─ manifest.json
│       └─ ...
├─ hacs.json
├─ README.md
└─ LICENSE
```

## Architecture

* Keep business logic separate from Home Assistant framework code
* Prefer clear module boundaries between domain logic, orchestration, and infrastructure
* Keep infrastructure concerns isolated from core business rules
* Design modules so they can be tested independently
* Keep state ownership explicit and local where possible
* Separate configuration, orchestration, and core logic
* Organise code by feature or domain once the integration grows

## Coding Standards

* Follow PEP 8 consistently
* Use meaningful names for variables, functions, classes, and modules
* Keep functions small and single-purpose
* Prefer explicit code over clever code
* Avoid deeply nested conditionals and prefer early returns
* Avoid magic strings and numbers by using constants where appropriate
* Prefer pathlib over os.path for file system paths
* Prefer f-strings for string formatting
* Avoid mutating function arguments
* Prefer pure functions when possible

## Typing

* Use type hints for public functions and methods
* Always type public function return values
* Prefer precise types over broad types
* Avoid Any unless there is no practical alternative
* Prefer object, Protocol, or specific unions over overly broad types
* Keep types close to the domain they represent
* Use typed models where they improve clarity
* Use Literal and discriminated-style shapes when modelling constrained states
* Model impossible states as impossible
* Use Optional only when a value is genuinely optional
* Keep generics meaningful and constrained

## Functions and APIs

* Keep function signatures simple and explicit
* Prefer keyword arguments when a function has several parameters
* Avoid boolean flag parameters when they significantly change behaviour
* Return consistent shapes from functions
* Avoid returning overly broad types
* Prefer explicit data structures over loosely shaped dictionaries where possible
* Keep side effects obvious
* Use dependency injection where it improves testability and separation
* Prefer overloads or separate functions when behaviour differs significantly
* Raise exceptions for exceptional cases rather than expected control flow

## Object-Oriented Design

* Use classes when they model real state or behaviour
* Prefer dataclasses for simple data containers
* Use properties sparingly and only when they add real value
* Prefer composition over inheritance
* Keep classes focused on one responsibility
* Avoid god objects with too many responsibilities
* Make immutable objects immutable where practical
* Use private or internal conventions consistently for implementation details

## Error Handling

* Create specific exception classes for meaningful error categories
* Do not swallow errors silently
* Catch exceptions at the right boundary
* Log enough context to diagnose problems
* Avoid broad except blocks unless you re-raise or handle deliberately
* Handle None, missing keys, and invalid input explicitly
* In library code, raise clear and predictable exceptions
* In application code, convert internal errors into safe user-facing messages at the boundary

## Asynchronous Programming

* Use async only when the workload benefits from it
* Do not mix sync and async styles unnecessarily
* Prefer asyncio for structured asynchronous workflows
* Always await created coroutines
* Avoid fire-and-forget tasks unless they are deliberate and supervised
* Use cancellation and timeouts where appropriate
* Keep async I/O separate from business logic where possible
* Use async clients consistently rather than mixing sync and async implementations

## Testing

* Write unit tests for business logic
* Use integration tests for real Home Assistant or API behaviour
* Keep tests deterministic and isolated
* Use fixtures deliberately and keep them understandable
* Prefer factories or builders for test data where helpful
* Mock external systems rather than internal implementation details
* Test edge cases and invalid inputs
* Keep test names behaviour-focused
* Keep tests fast enough to run regularly
* Avoid coupling tests to internal implementation unless necessary

## Configuration and Secrets

* Keep configuration in Home Assistant config entries, options flows, or integration storage as appropriate
* Validate configuration at startup
* Do not hardcode secrets in source code
* Keep default values explicit
* Separate configuration models from business logic models

## Logging and Observability

* Use the logging module rather than print for application logging
* Avoid logging sensitive data
* Include contextual information that helps diagnose failures
* Keep log levels meaningful and consistent

## Performance

* Measure before optimizing
* Prefer simple code unless profiling shows a bottleneck
* Avoid unnecessary allocations in hot paths
* Use generators for streaming large sequences
* Be careful with repeated copying of large lists and dictionaries
* Cache expensive computations only when it is safe and useful
* Use appropriate data structures for access patterns
* Avoid premature optimization

## Security

* Treat all external input as untrusted
* Validate and sanitize input where appropriate
* Avoid deserializing untrusted data unsafely
* Be careful with subprocess usage and shell execution
* Do not trust client-side validation as security
* Store secrets securely
* Keep dependencies updated
* Apply least privilege to credentials and service accounts

## Maintainability

* Keep modules small and cohesive
* Avoid circular imports
* Refactor duplication only when the duplication is real
* Remove dead code and unused dependencies regularly
* Document non-obvious design decisions
* Keep public APIs of modules small
* Keep comments focused on intent rather than restating code
* Review code for readability as well as correctness

## Recommended Folder Structure

* Keep coordinator, entity, and platform modules focused on one job
* Keep reusable domain logic separate from Home Assistant integration glue
* Keep tests close in structure to the code they exercise
* Avoid a giant shared utils package

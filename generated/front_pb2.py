# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: front.proto
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x0b\x66ront.proto\x12\x05\x66ront\"q\n\x0c\x46rontRequest\x12\x14\n\x0crequest_type\x18\x01 \x01(\t\x12\x14\n\x0cuse_deadline\x18\x02 \x01(\x08\x12\x1b\n\x13use_circuit_breaker\x18\x03 \x01(\x08\x12\x18\n\x10use_backpressure\x18\x04 \x01(\x08\"G\n\rFrontResponse\x12\x0e\n\x06result\x18\x01 \x01(\t\x12\x0f\n\x07success\x18\x02 \x01(\x08\x12\x15\n\rerror_message\x18\x03 \x01(\t2J\n\x0c\x46rontService\x12:\n\rSubmitRequest\x12\x13.front.FrontRequest\x1a\x14.front.FrontResponseb\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'front_pb2', _globals)
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  _globals['_FRONTREQUEST']._serialized_start=22
  _globals['_FRONTREQUEST']._serialized_end=135
  _globals['_FRONTRESPONSE']._serialized_start=137
  _globals['_FRONTRESPONSE']._serialized_end=208
  _globals['_FRONTSERVICE']._serialized_start=210
  _globals['_FRONTSERVICE']._serialized_end=284
# @@protoc_insertion_point(module_scope)

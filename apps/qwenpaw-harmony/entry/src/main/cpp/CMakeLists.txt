# atls —— 自研 HTTP/1.1 + TLS 传输层（OpenSSL 3.5.9 静态链接，NAPI 导出）
#
# 构建由 hvigor 驱动（entry/build-profile.json5 的 externalNativeOptions），
# 工具链经 NDK 的 ohos.toolchain.cmake 注入——本文件不写 toolchain。
# 产物 libatls.so 由 ArkTS 侧 import from 'libatls.so' 消费。
cmake_minimum_required(VERSION 3.4.1)
project(atls C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)

# OpenSSL 预构建静态库（来源与重建步骤见 third_party/openssl/README）。
# 按 NDK 注入的 OHOS_ARCH 选 ABI：arm64-v8a（真机）/ x86_64（模拟器）。
if(OHOS_ARCH STREQUAL "x86_64")
  set(ATLS_OSSL_DIR ${CMAKE_CURRENT_SOURCE_DIR}/third_party/openssl-x86_64)
else()
  set(ATLS_OSSL_DIR ${CMAKE_CURRENT_SOURCE_DIR}/third_party/openssl)
endif()

# 链接顺序：libssl 先于 libcrypto。
add_library(openssl_ssl STATIC IMPORTED)
set_target_properties(openssl_ssl PROPERTIES
  IMPORTED_LOCATION ${ATLS_OSSL_DIR}/lib/libssl.a)

add_library(openssl_crypto STATIC IMPORTED)
set_target_properties(openssl_crypto PROPERTIES
  IMPORTED_LOCATION ${ATLS_OSSL_DIR}/lib/libcrypto.a)

add_library(atls SHARED
  atls_http.c
  napi_init.cpp)

target_include_directories(atls PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}
  ${ATLS_OSSL_DIR}/include)

# libace_napi.z.so 按名链接（系统库，NDK sysroot 提供）
target_link_libraries(atls
  openssl_ssl
  openssl_crypto
  libace_napi.z.so)

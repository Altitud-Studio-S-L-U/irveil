cmake_minimum_required(VERSION 3.20)
project(IRVeil VERSION 0.2.1 LANGUAGES C CXX)

find_package(LLVM REQUIRED CONFIG)
if(NOT LLVM_VERSION_MAJOR EQUAL 18)
  message(FATAL_ERROR "IRVeil supports LLVM 18 only; found ${LLVM_PACKAGE_VERSION}")
endif()
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64)$")
  message(FATAL_ERROR "IRVeil is validated for Linux x86-64 only")
endif()

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

add_library(IRVeilCore STATIC src/Pass.cpp)
add_library(IRVeil::Core ALIAS IRVeilCore)
set_target_properties(IRVeilCore PROPERTIES POSITION_INDEPENDENT_CODE ON EXPORT_NAME Core)
target_compile_features(IRVeilCore PUBLIC cxx_std_17)
target_include_directories(IRVeilCore PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)
target_include_directories(IRVeilCore SYSTEM PUBLIC ${LLVM_INCLUDE_DIRS})
separate_arguments(IRVEIL_LLVM_DEFINITIONS NATIVE_COMMAND "${LLVM_DEFINITIONS}")
target_compile_options(IRVeilCore PUBLIC ${IRVEIL_LLVM_DEFINITIONS})
target_compile_options(IRVeilCore PRIVATE -Wall -Wextra -Wpedantic)
if(NOT LLVM_ENABLE_RTTI)
  target_compile_options(IRVeilCore PUBLIC -fno-rtti)
endif()
target_link_libraries(IRVeilCore PUBLIC LLVM)

add_library(IRVeilHeaders INTERFACE)
add_library(IRVeil::Headers ALIAS IRVeilHeaders)
set_target_properties(IRVeilHeaders PROPERTIES EXPORT_NAME Headers)
target_include_directories(IRVeilHeaders INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)

configure_file(src/Version.h.in generated/Version.h @ONLY)
add_library(IRVeilPass MODULE src/Plugin.cpp)
add_library(IRVeil::Pass ALIAS IRVeilPass)
set_target_properties(IRVeilPass PROPERTIES PREFIX "" EXPORT_NAME Pass)
target_include_directories(IRVeilPass PRIVATE ${CMAKE_CURRENT_BINARY_DIR}/generated)
target_link_libraries(IRVeilPass PRIVATE IRVeil::Core)
target_compile_options(IRVeilPass PRIVATE -Wall -Wextra -Wpedantic)

install(TARGETS IRVeilCore EXPORT IRVeilTargets ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR})
install(TARGETS IRVeilPass EXPORT IRVeilPluginTargets LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}/irveil)
install(TARGETS IRVeilHeaders EXPORT IRVeilPluginTargets)
install(DIRECTORY include/irveil DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(EXPORT IRVeilTargets NAMESPACE IRVeil:: DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/IRVeil)
install(EXPORT IRVeilPluginTargets NAMESPACE IRVeil:: DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/IRVeil)
configure_package_config_file(cmake/IRVeilConfig.cmake.in
  ${CMAKE_CURRENT_BINARY_DIR}/IRVeilConfig.cmake
  INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/IRVeil)
write_basic_package_version_file(${CMAKE_CURRENT_BINARY_DIR}/IRVeilConfigVersion.cmake
  VERSION ${PROJECT_VERSION} COMPATIBILITY SameMajorVersion)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/IRVeilConfig.cmake
  ${CMAKE_CURRENT_BINARY_DIR}/IRVeilConfigVersion.cmake
  cmake/IRVeilTarget.cmake
  DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/IRVeil)

include(CTest)
if(BUILD_TESTING)
  find_package(Python3 3.8 REQUIRED COMPONENTS Interpreter)
  add_test(NAME irveil-contract
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_irveil.py
      --plugin $<TARGET_FILE:IRVeilPass> --core $<TARGET_FILE:IRVeilCore>
      --llvm-bin ${LLVM_TOOLS_BINARY_DIR} --include ${CMAKE_CURRENT_SOURCE_DIR}/include)
  add_test(NAME irveil-re-harness
    COMMAND ${Python3_EXECUTABLE} -m unittest discover
      -s ${CMAKE_CURRENT_SOURCE_DIR}/tools/re -p "tests_*.py")
  add_test(NAME irveil-installed-consumer
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_installed_package.py
      --build-dir ${CMAKE_CURRENT_BINARY_DIR} --cmake ${CMAKE_COMMAND}
      --llvm-bin ${LLVM_TOOLS_BINARY_DIR} --configuration $<CONFIG>)
  add_test(NAME irveil-compiler-consumer
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_compiler_package.py
      --build-dir ${CMAKE_CURRENT_BINARY_DIR} --cmake ${CMAKE_COMMAND}
      --llvm-bin ${LLVM_TOOLS_BINARY_DIR} --configuration $<CONFIG>)
endif()

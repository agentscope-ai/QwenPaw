require 'json'

package = JSON.parse(File.read(File.join(__dir__, '..', 'package.json')))

Pod::Spec.new do |spec|
  spec.name = 'QwenPawOAuthLoopback'
  spec.version = package['version']
  spec.summary = package['description']
  spec.description = package['description']
  spec.license = package['license']
  spec.author = 'QwenPaw'
  spec.homepage = 'https://github.com/agentscope-ai/QwenPaw'
  spec.platforms = { :ios => '16.4' }
  spec.swift_version = '5.9'
  spec.source = { :path => '.' }
  spec.static_framework = true

  spec.dependency 'ExpoModulesCore'
  spec.source_files = '**/*.swift'
end

import 'dart:convert';
import 'dart:io';

import 'package:analyzer/dart/analysis/utilities.dart';
import 'package:analyzer/dart/ast/ast.dart';
import 'package:analyzer/dart/ast/visitor.dart';

int codeLines(String text) {
  return text.split(RegExp(r'\r?\n')).where((line) => line.trim().isNotEmpty).length;
}

String firstLine(String text) {
  return text
      .split(RegExp(r'\r?\n'))
      .firstWhere((line) => line.trim().isNotEmpty, orElse: () => '')
      .trim();
}

class IdentifierCollector extends RecursiveAstVisitor<void> {
  IdentifierCollector(this.names, this.self);

  final Set<String> names;
  final String self;
  final Set<String> refs = <String>{};

  @override
  void visitSimpleIdentifier(SimpleIdentifier node) {
    final name = node.name;
    if (name != self && names.contains(name)) {
      refs.add(name);
    }
    super.visitSimpleIdentifier(node);
  }
}

String? declarationName(CompilationUnitMember declaration) {
  if (declaration is NamedCompilationUnitMember) {
    return declaration.name.lexeme;
  }
  if (declaration is TopLevelVariableDeclaration) {
    final variables = declaration.variables.variables;
    if (variables.length == 1) {
      return variables.first.name.lexeme;
    }
  }
  return null;
}

String declarationKind(CompilationUnitMember declaration) {
  if (declaration is ClassDeclaration) {
    return 'ClassDeclaration';
  }
  if (declaration is MixinDeclaration) {
    return 'MixinDeclaration';
  }
  if (declaration is EnumDeclaration) {
    return 'EnumDeclaration';
  }
  if (declaration is ExtensionDeclaration) {
    return 'ExtensionDeclaration';
  }
  if (declaration is FunctionDeclaration) {
    return 'FunctionDeclaration';
  }
  if (declaration is TopLevelVariableDeclaration) {
    return 'TopLevelVariableDeclaration';
  }
  return declaration.runtimeType.toString();
}

Map<String, Object?> flutterMeta(CompilationUnitMember declaration, String body) {
  final tags = <String>[];
  final meta = <String, Object?>{};
  final isWidget = body.contains(RegExp(r'\b(StatelessWidget|StatefulWidget|InheritedWidget)\b')) ||
      body.contains(RegExp(r'\bWidget\s+build\s*\('));
  if (isWidget) {
    tags.add('flutter_widget');
  }
  if (body.contains(RegExp(r'\bState<\s*[A-Za-z_]\w*\s*>'))) {
    tags.add('flutter_state');
  }
  if (body.contains(RegExp(r'\bBuildContext\b'))) {
    meta['uses_build_context'] = true;
  }
  return <String, Object?>{
    'tags': tags,
    'meta': meta,
  };
}

List<Map<String, Object?>> declarationChildren(
  CompilationUnitMember declaration,
  String source,
  LineInfo lineInfo,
) {
  if (declaration is! ClassDeclaration) {
    return <Map<String, Object?>>[];
  }
  final children = <Map<String, Object?>>[];
  for (final member in declaration.members) {
    String? name;
    final tags = <String>['method'];
    if (member is MethodDeclaration) {
      name = member.name.lexeme;
      if (name == 'build') {
        tags.add('flutter_build');
      }
    } else if (member is ConstructorDeclaration) {
      name = member.name?.lexeme;
      name = name == null || name.isEmpty ? 'constructor' : 'constructor.$name';
      tags.add('constructor');
    }
    if (name == null) {
      continue;
    }
    final body = source.substring(member.offset, member.end);
    children.add(<String, Object?>{
      'name': name,
      'kind': member.runtimeType.toString(),
      'signature': firstLine(body),
      'start_line': lineInfo.getLocation(member.offset).lineNumber,
      'end_line': lineInfo.getLocation(member.end).lineNumber,
      'code_lines': codeLines(body),
      'tags': tags,
      'meta': <String, Object?>{},
    });
  }
  return children;
}

void main(List<String> args) {
  if (args.isEmpty) {
    stderr.writeln('usage: source_split_dart_ast.dart <file>');
    exit(1);
  }
  final filePath = args.first;
  final source = File(filePath).readAsStringSync();
  final parsed = parseFile(path: filePath);
  final unit = parsed.unit;
  final lineInfo = parsed.lineInfo;
  final declarations = unit.declarations;
  final names = declarations.map(declarationName).whereType<String>().toSet();

  final symbols = <Map<String, Object?>>[];
  for (final declaration in declarations) {
    final name = declarationName(declaration);
    if (name == null) {
      continue;
    }
    final body = source.substring(declaration.offset, declaration.end);
    final collector = IdentifierCollector(names, name);
    declaration.accept(collector);
    final flutter = flutterMeta(declaration, body);
    symbols.add(<String, Object?>{
      'name': name,
      'kind': declarationKind(declaration),
      'signature': firstLine(body),
      'start_line': lineInfo.getLocation(declaration.offset).lineNumber,
      'end_line': lineInfo.getLocation(declaration.end).lineNumber,
      'code_lines': codeLines(body),
      'references': collector.refs.toList()..sort(),
      'tags': flutter['tags'],
      'meta': flutter['meta'],
      'children': declarationChildren(declaration, source, lineInfo),
    });
  }

  stdout.writeln(jsonEncode(<String, Object?>{
    'parser': <String, Object?>{
      'parser': 'dart_analyzer_ast',
      'strategy': 'package_analyzer_parse_file',
      'precision': 'semantic_top_level',
      'available': true,
    },
    'symbols': symbols,
  }));
}

import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

guard CommandLine.arguments.count == 2 else {
    fputs("usage: generate-app-icon.swift <iconset-directory>\n", stderr)
    exit(2)
}

let iconsetURL = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let fileManager = FileManager.default
try fileManager.createDirectory(at: iconsetURL, withIntermediateDirectories: true)

let iconSizes: [(name: String, pixels: Int)] = [
    ("16x16", 16),
    ("16x16@2x", 32),
    ("32x32", 32),
    ("32x32@2x", 64),
    ("128x128", 128),
    ("128x128@2x", 256),
    ("256x256", 256),
    ("256x256@2x", 512),
    ("512x512", 512),
    ("512x512@2x", 1024),
]

let canvas = CGFloat(1024)
let colorSpace = CGColorSpaceCreateDeviceRGB()

func color(_ red: CGFloat, _ green: CGFloat, _ blue: CGFloat, _ alpha: CGFloat = 1) -> CGColor {
    CGColor(colorSpace: colorSpace, components: [red, green, blue, alpha])!
}

func drawIcon(in context: CGContext) {
    context.setAllowsAntialiasing(true)
    context.setShouldAntialias(true)
    context.interpolationQuality = .high
    context.setFillColor(color(0.055, 0.047, 0.043))
    context.fill(CGRect(x: 0, y: 0, width: canvas, height: canvas))

    let cardRect = CGRect(x: 72, y: 72, width: 880, height: 880)
    let cardPath = CGPath(roundedRect: cardRect, cornerWidth: 218, cornerHeight: 218, transform: nil)
    context.saveGState()
    context.addPath(cardPath)
    context.setShadow(offset: CGSize(width: 0, height: -28), blur: 48, color: color(0, 0, 0, 0.34))
    context.clip()

    let gradient = CGGradient(
        colorsSpace: colorSpace,
        colors: [color(0.98, 0.68, 0.46), color(0.76, 0.37, 0.29)] as CFArray,
        locations: [0, 1]
    )!
    context.drawLinearGradient(
        gradient,
        start: CGPoint(x: 130, y: 910),
        end: CGPoint(x: 900, y: 100),
        options: []
    )

    context.setFillColor(color(1, 1, 1, 0.08))
    context.fillEllipse(in: CGRect(x: 140, y: 600, width: 520, height: 520))
    context.restoreGState()

    context.addPath(cardPath)
    context.setStrokeColor(color(1, 1, 1, 0.32))
    context.setLineWidth(8)
    context.strokePath()

    // A compact, legible P that echoes the editor's warm accent and monogram.
    context.setStrokeColor(color(0.16, 0.10, 0.08))
    context.setLineWidth(92)
    context.setLineCap(.round)
    context.setLineJoin(.round)
    let stem = CGMutablePath()
    stem.move(to: CGPoint(x: 376, y: 760))
    stem.addLine(to: CGPoint(x: 376, y: 264))
    context.addPath(stem)
    context.strokePath()

    let bowl = CGMutablePath()
    bowl.move(to: CGPoint(x: 380, y: 700))
    bowl.addCurve(
        to: CGPoint(x: 666, y: 505),
        control1: CGPoint(x: 684, y: 748),
        control2: CGPoint(x: 684, y: 505)
    )
    bowl.addCurve(
        to: CGPoint(x: 380, y: 505),
        control1: CGPoint(x: 520, y: 505),
        control2: CGPoint(x: 432, y: 505)
    )
    context.addPath(bowl)
    context.strokePath()

    // Three understated lines suggest writing without competing with the monogram.
    context.setStrokeColor(color(0.16, 0.10, 0.08, 0.34))
    context.setLineWidth(18)
    context.setLineCap(.round)
    for (index, width) in [152, 112, 76].enumerated() {
        let y = CGFloat(306 - (index * 54))
        context.move(to: CGPoint(x: 602, y: y))
        context.addLine(to: CGPoint(x: 602 + CGFloat(width), y: y))
    }
    context.strokePath()
}

for iconSize in iconSizes {
    let size = iconSize.pixels
    guard let context = CGContext(
        data: nil,
        width: size,
        height: size,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        fatalError("Unable to create icon rendering context")
    }

    context.saveGState()
    context.scaleBy(x: CGFloat(size) / canvas, y: CGFloat(size) / canvas)
    drawIcon(in: context)
    context.restoreGState()

    guard let image = context.makeImage() else {
        fatalError("Unable to render app icon")
    }

    let outputURL = iconsetURL.appendingPathComponent("icon_\(iconSize.name).png")
    guard let destination = CGImageDestinationCreateWithURL(
        outputURL as CFURL,
        UTType.png.identifier as CFString,
        1,
        nil
    ) else {
        fatalError("Unable to create PNG destination")
    }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        fatalError("Unable to write \(outputURL.path)")
    }
}

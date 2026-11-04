package app.sonus.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonus.ui.theme.LocalSonusColors

/** The background of the app: the dark colour with soft coloured light at the top and at the bottom (like the glow of the PC app). */
@Composable
fun AuroraBackground(tint: Color? = null, modifier: Modifier = Modifier, content: @Composable BoxScope.() -> Unit) {
    val colors = LocalSonusColors.current
    val topColor by animateColorAsState(tint ?: colors.accent, label = "auroraTint")
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(colors.background)
            .drawBehind {
                drawRect(
                    Brush.radialGradient(
                        listOf(topColor.copy(alpha = 0.34f), Color.Transparent),
                        center = Offset(size.width * 0.12f, -size.height * 0.02f),
                        radius = size.width * 1.05f,
                    ),
                )
                drawRect(
                    Brush.radialGradient(
                        listOf(colors.accent.copy(alpha = 0.13f), Color.Transparent),
                        center = Offset(size.width * 1.0f, size.height * 0.95f),
                        radius = size.width * 0.9f,
                    ),
                )
            },
        content = content,
    )
}

/** A panel of "glass": see-through, with a soft light border. [base] adds a dark layer when it sits over moving content. */
@Composable
fun GlassSurface(
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(20.dp),
    strong: Boolean = false,
    base: Color = Color.Transparent,
    onClick: (() -> Unit)? = null,
    content: @Composable BoxScope.() -> Unit,
) {
    val fill = Brush.linearGradient(
        listOf(Color.White.copy(alpha = if (strong) 0.15f else 0.09f), Color.White.copy(alpha = if (strong) 0.07f else 0.035f)),
    )
    val border = BorderStroke(
        1.dp,
        Brush.linearGradient(listOf(Color.White.copy(alpha = 0.26f), Color.White.copy(alpha = 0.04f), Color.White.copy(alpha = 0.10f))),
    )
    var chain = modifier.clip(shape).background(base).background(fill).border(border, shape)
    if (onClick != null) chain = chain.clickable(onClick = onClick)
    Box(modifier = chain, content = content)
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier, trailing: (@Composable () -> Unit)? = null) {
    Row(
        modifier = modifier.fillMaxWidth().padding(horizontal = 20.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onBackground)
        trailing?.invoke()
    }
}

@Composable
fun ScreenTitle(text: String, modifier: Modifier = Modifier, trailing: (@Composable () -> Unit)? = null) {
    Row(
        modifier = modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text, fontSize = 30.sp, fontWeight = FontWeight.ExtraBold, color = MaterialTheme.colorScheme.onBackground)
        trailing?.invoke()
    }
}

@Composable
fun GlassChip(text: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val colors = LocalSonusColors.current
    val shape = RoundedCornerShape(50)
    if (selected) {
        Box(
            modifier = modifier.clip(shape).background(colors.accent).clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 9.dp),
            contentAlignment = Alignment.Center,
        ) { Text(text, color = colors.accentText, fontWeight = FontWeight.SemiBold, fontSize = 14.sp) }
    } else {
        GlassSurface(modifier = modifier, shape = shape, onClick = onClick) {
            Text(text, color = colors.text, fontSize = 14.sp, modifier = Modifier.padding(horizontal = 16.dp, vertical = 9.dp))
        }
    }
}

/** The main button: accent colour, round. */
@Composable
fun AccentButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, icon: ImageVector? = null) {
    val colors = LocalSonusColors.current
    Row(
        modifier = modifier.clip(RoundedCornerShape(50)).background(colors.accent).clickable(onClick = onClick)
            .padding(horizontal = 20.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        if (icon != null) {
            Icon(icon, contentDescription = null, tint = colors.accentText, modifier = Modifier.size(20.dp))
            Box(modifier = Modifier.size(6.dp))
        }
        Text(text, color = colors.accentText, fontWeight = FontWeight.Bold, fontSize = 15.sp)
    }
}

/** The second button: glass. */
@Composable
fun GlassButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, icon: ImageVector? = null) {
    val colors = LocalSonusColors.current
    GlassSurface(modifier = modifier, shape = RoundedCornerShape(50), onClick = onClick) {
        Row(
            modifier = Modifier.padding(horizontal = 20.dp, vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.Center,
        ) {
            if (icon != null) {
                Icon(icon, contentDescription = null, tint = colors.text, modifier = Modifier.size(20.dp))
                Box(modifier = Modifier.size(6.dp))
            }
            Text(text, color = colors.text, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
        }
    }
}

/** A round icon button on glass. */
@Composable
fun GlassIconButton(icon: ImageVector, description: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val colors = LocalSonusColors.current
    GlassSurface(modifier = modifier.size(42.dp), shape = CircleShape, onClick = onClick) {
        Icon(icon, contentDescription = description, tint = colors.text, modifier = Modifier.size(22.dp).align(Alignment.Center))
    }
}

@Composable
fun EmptyState(icon: ImageVector, title: String, text: String, modifier: Modifier = Modifier, actions: (@Composable () -> Unit)? = null) {
    val colors = LocalSonusColors.current
    androidx.compose.foundation.layout.Column(
        modifier = modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 40.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(
            modifier = Modifier.size(84.dp).clip(CircleShape).background(Brush.radialGradient(listOf(colors.accent.copy(alpha = 0.30f), Color.Transparent))),
            contentAlignment = Alignment.Center,
        ) { Icon(icon, contentDescription = null, tint = colors.accent, modifier = Modifier.size(40.dp)) }
        Text(title, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = colors.text)
        Text(text, color = colors.subtext, fontSize = 14.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        if (actions != null) {
            Box(modifier = Modifier.height(4.dp))
            actions()
        }
    }
}


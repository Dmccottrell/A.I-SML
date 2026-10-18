package app.emvryx.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import app.emvryx.android.ui.theme.Emvryx

@Composable
fun SignInScreen(vm: AppViewModel) {
    var way by rememberSaveable { mutableStateOf(SignInWay.Password) }
    var id by rememberSaveable { mutableStateOf("") }
    var secret by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
    var showServer by rememberSaveable { mutableStateOf(false) }
    val twoStep = vm.twoStepTicket != null

    Box(Modifier.fillMaxSize().safeDrawingPadding().imePadding(), contentAlignment = Alignment.Center) {
        Column(
            Modifier.widthIn(max = 420.dp).fillMaxWidth().verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Logo(Modifier.size(56.dp))
            Text("Sign in to Emvryx", style = MaterialTheme.typography.headlineSmall)

            if (twoStep) {
                Text("Enter the 6-digit code from your authenticator app, or one of your recovery codes.", color = Emvryx.muted)
                OutlinedTextField(
                    code, { code = it }, Modifier.fillMaxWidth(), label = { Text("Code") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number, imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { vm.submitTwoStep(code) }),
                )
            } else {
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    SignInWay.entries.forEachIndexed { i, w ->
                        SegmentedButton(
                            selected = way == w, onClick = { way = w },
                            shape = SegmentedButtonDefaults.itemShape(i, SignInWay.entries.size),
                        ) { Text(if (w == SignInWay.Password) "Password" else "Key") }
                    }
                }
                if (way == SignInWay.Password) {
                    OutlinedTextField(
                        id, { id = it }, Modifier.fillMaxWidth(), label = { Text("Name or email") }, singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                    )
                }
                OutlinedTextField(
                    secret, { secret = it }, Modifier.fillMaxWidth(),
                    label = { Text(if (way == SignInWay.Password) "Password" else "Your key") }, singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { vm.signIn(way, id, secret) }),
                )
                if (showServer) {
                    OutlinedTextField(
                        vm.server, { vm.server = it }, Modifier.fillMaxWidth(), label = { Text("Server address") }, singleLine = true,
                        supportingText = { Text("Your Emvryx address, e.g. https://chat.emvryx.app") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    )
                }
            }

            vm.signInError?.let { Text(it, color = MaterialTheme.colorScheme.error) }

            Button(
                onClick = { if (twoStep) vm.submitTwoStep(code) else vm.signIn(way, id, secret) },
                enabled = !vm.signInBusy && (if (twoStep) code.isNotBlank() else secret.isNotBlank() && (way == SignInWay.Key || id.isNotBlank())),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                if (vm.signInBusy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = Emvryx.text)
                else Text(if (twoStep) "Continue" else "Sign in")
            }
            if (twoStep) {
                TextButton(onClick = vm::cancelTwoStep) { Text("Back") }
            } else {
                TextButton(onClick = { showServer = !showServer }) {
                    Text(if (showServer) "Hide server address" else "Server: ${vm.server.substringAfter("://")}", color = Emvryx.muted)
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}
